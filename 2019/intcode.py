from __future__ import annotations

import operator
from dataclasses import dataclass
from functools import partial
from enum import Enum
from typing import (
    cast,
    Any,
    Callable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    TYPE_CHECKING,
)


Memory = List[int]


class Halt(Exception):
    """Signal to end the program"""

    @classmethod
    def halt(cls) -> None:
        raise cls


class _ParameterGetter(Protocol):
    def __call__(self, memory: Memory, arg: int) -> int:
        ...


_getters: Sequence[_ParameterGetter] = [
    cast(_ParameterGetter, operator.getitem),
    lambda _, a: a,
]


class ParameterMode(Enum):
    # modes are an integer (0-9) mapping to a _ParameterGetter definition
    position = 0
    immediate = 1

    if TYPE_CHECKING:
        get: _ParameterGetter

    def __new__(cls, value: int) -> ParameterMode:
        mode = object.__new__(cls)
        mode._value_ = value
        mode.get = _getters[value]
        return mode


@dataclass
class Instruction:
    # the inputs are processed by a function that operates on arg_count integers
    f: Callable[..., Any]
    # An opcode takes N parameters, consisting of M arguments and an optional output
    arg_count: int = 0
    output: bool = False

    def __call__(self, pos: int, *args: int) -> Tuple[int, Any]:
        """Produce a new CPU position and a result"""
        offset = self.arg_count + int(self.output)
        return pos + 1 + offset, self.f(*args)

    def bind(self, opcode: int, cpu: CPU) -> BoundInstruction:
        # assumption: on binding, cpu.pos points to the position in memory
        # for our opcode.
        modes = opcode // 100
        return BoundInstruction(
            self,
            tuple(
                ParameterMode(modes // (10 ** i) % 10) for i in range(self.arg_count)
            ),
            cpu.pos + 1,
            cpu,
        )


@dataclass
class JumpInstruction(Instruction):
    def __call__(self, pos: int, *args: int) -> Tuple[int, Any]:
        """Use last argument as jump target if result is true-ish"""
        *jmpargs, jump_to = args
        offset, result = super().__call__(pos, *jmpargs)
        return jump_to if result else offset, result


@dataclass
class BoundInstruction:
    instruction: Instruction
    modes: Tuple[ParameterMode, ...]
    # where to read the arg values from
    offset: int
    cpu: CPU

    def __call__(self) -> int:
        mem, pos, instr = (
            self.cpu.memory,
            self.cpu.pos,
            self.instruction,
        )
        # apply each parameter mode to the memory values
        args = (
            param.get(mem, mem[i])
            for i, param in enumerate(self.modes, start=self.offset)
        )
        newpos, result = instr(pos, *args)
        if instr.output:
            target = mem[self.offset + instr.arg_count]
            mem[target] = int(result)
        return newpos


InstructionSet = Mapping[int, Instruction]


class CPU:
    memory: Memory
    pos: int
    opcodes: InstructionSet

    def __init__(self, opcodes: InstructionSet) -> None:
        self.opcodes = opcodes

    def __getitem__(self, opcode: int) -> BoundInstruction:
        return self.opcodes[opcode % 100].bind(opcode, self)

    def reset(self, memory: Memory = None) -> None:
        if memory is None:
            memory = []
        self.memory = memory[:]
        self.pos: int = 0

    def execute(self, memory: Memory,) -> None:
        self.reset(memory)
        mem = self.memory
        try:
            while True:
                self.pos = self[mem[self.pos]]()
        except Halt:
            return


base_opcodes = {
    1: Instruction(operator.add, 2, True),
    2: Instruction(operator.mul, 2, True),
    3: Instruction(partial(input, "i> "), output=True),
    4: Instruction(print, 1),
    5: JumpInstruction(bool, 2),
    6: JumpInstruction(operator.not_, 2),
    7: Instruction(operator.lt, 2, True),
    8: Instruction(operator.eq, 2, True),
    99: Instruction(Halt.halt),
}


def ioset(
    *inputs: int, opcodes: Optional[InstructionSet] = None
) -> Tuple[List[int], InstructionSet]:
    """Create an output list and instructionset with given input"""
    if opcodes is None:
        opcodes = {}
    outputs: List[int] = []
    get_input = partial(next, iter(inputs))
    return (
        outputs,
        {
            **base_opcodes,
            **opcodes,
            3: Instruction(get_input, output=True),
            4: Instruction(outputs.append, 1),
        },
    )


if __name__ == "__main__":
    test_mem = [1, 9, 10, 3, 2, 3, 11, 0, 99, 30, 40, 50]
    cpu = CPU(base_opcodes)
    cpu.reset(test_mem).execute()
    assert cpu.memory[0] == 3500

    def test_jumpcodes(instr: Memory, tests: Mapping[int, int]) -> None:
        for inp, expected in tests.items():
            outputs, test_opcodes = ioset(inp)
            CPU(test_opcodes).reset(instr).execute()
            assert outputs == [expected]

    test_tests = (
        # input == 8, position mode
        ([3, 9, 8, 9, 10, 9, 4, 9, 99, -1, 8], {8: 1, 7: 0}),
        # input < 8, position mode
        ([3, 9, 7, 9, 10, 9, 4, 9, 99, -1, 8], {7: 1, 8: 0}),
        # input == 8, immediate mode
        ([3, 3, 1108, -1, 8, 3, 4, 3, 99], {8: 1, 7: 0}),
        # input < 8, position mode
        ([3, 3, 1107, -1, 8, 3, 4, 3, 99], {7: 1, 8: 0}),
        # cmp(input, 8), producing 999, 1000, 1001
        (
            [
                3,
                21,
                1008,
                21,
                8,
                20,
                1005,
                20,
                22,
                107,
                8,
                21,
                20,
                1006,
                20,
                31,
                1106,
                0,
                36,
                98,
                0,
                0,
                1002,
                21,
                125,
                20,
                4,
                20,
                1105,
                1,
                46,
                104,
                999,
                1105,
                1,
                46,
                1101,
                1000,
                1,
                20,
                4,
                20,
                1105,
                1,
                46,
                98,
                99,
            ],
            {7: 999, 8: 1000, 42: 1001},
        ),
    )
    for test in test_tests:
        test_jumpcodes(*test)
