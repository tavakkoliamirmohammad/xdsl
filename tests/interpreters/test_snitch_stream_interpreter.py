import pytest

from xdsl.builder import ImplicitBuilder
from xdsl.dialects import riscv, riscv_snitch, snitch_stream, stream
from xdsl.dialects.builtin import ArrayAttr, ModuleOp
from xdsl.interpreter import Interpreter
from xdsl.interpreters.riscv import RawPtr, RiscvFunctions
from xdsl.interpreters.riscv_snitch import RiscvSnitchFunctions
from xdsl.interpreters.snitch_stream import SnitchStreamFunctions
from xdsl.ir import Block, Region
from xdsl.utils.test_value import TestSSAValue


@pytest.mark.parametrize(
    "ub, strides, offsets",
    [
        ((6,), (1,), tuple(range(6))),
        ((6,), (2,), tuple(range(0, 12, 2))),
        ((2, 3), (1, 2), tuple(range(6))),
        ((2, 3, 4), (1, 2, 6), tuple(range(24))),
    ],
)
def test_stride_pattern_offsets(
    ub: tuple[int, ...], strides: tuple[int, ...], offsets: tuple[int, ...]
):
    assert (
        snitch_stream.StridePattern.from_bounds_and_strides(ub, strides).offsets()
        == offsets
    )


@pytest.mark.parametrize(
    "inputs, outputs",
    [
        (((24,), (1,)), ((24,), (1,))),
        (((4, 3, 2), (1, 4, 12)), ((24,), (1,))),
        (((2, 3), (8, 16)), ((6,), (8,))),
        (((2, 3), (0, 8)), ((2, 3), (0, 8))),
        (((2, 3), (8, 0)), ((2, 3), (8, 0))),
        (((3, 3, 1, 6, 1, 1), (1, 2, 3, 4, 5, 6)), ((3, 3, 6), (1, 2, 4))),
    ],
)
def test_simplify_stride_pattern(
    inputs: tuple[tuple[int, ...], tuple[int, ...]],
    outputs: tuple[tuple[int, ...], tuple[int, ...]],
):
    assert snitch_stream.StridePattern.from_bounds_and_strides(
        *inputs
    ).simplified() == snitch_stream.StridePattern.from_bounds_and_strides(*outputs)


def test_snitch_stream_interpreter():
    register = riscv.IntRegisterType.unallocated()

    interpreter = Interpreter(ModuleOp([]))
    interpreter.register_implementations(RiscvFunctions())
    interpreter.register_implementations(SnitchStreamFunctions())
    interpreter.register_implementations(RiscvSnitchFunctions())

    a = RawPtr.new_float64([2.0] * 6)
    b = RawPtr.new_float64([3.0] * 6)
    c = RawPtr.new_float64([4.0] * 6)

    streaming_region_body = Region(
        Block(
            arg_types=(
                stream.ReadableStreamType(riscv.Registers.FT0),
                stream.ReadableStreamType(riscv.Registers.FT1),
                stream.WritableStreamType(riscv.Registers.FT2),
            )
        )
    )

    with ImplicitBuilder(streaming_region_body) as (a_stream, b_stream, c_stream):
        count_reg = riscv.LiOp(5).rd

        frep_body = Region(Block())

        with ImplicitBuilder(frep_body):
            a_reg = riscv_snitch.ReadOp(a_stream).res
            b_reg = riscv_snitch.ReadOp(b_stream).res
            c_reg = riscv.FAddDOp(a_reg, b_reg, rd=riscv.Registers.FT2).rd
            riscv_snitch.WriteOp(c_reg, c_stream)

        riscv_snitch.FrepOuter(count_reg, frep_body)

    assert (
        interpreter.run_op(
            snitch_stream.StreamingRegionOp(
                (TestSSAValue(register), TestSSAValue(register)),
                (TestSSAValue(register),),
                ArrayAttr(
                    (
                        snitch_stream.StridePattern.from_bounds_and_strides(
                            [3, 2], [8, 24]
                        ),
                    )
                ),
                streaming_region_body,
            ),
            (a, b, c),
        )
        == ()
    )

    assert c.float64.get_list(6) == [5.0] * 6
