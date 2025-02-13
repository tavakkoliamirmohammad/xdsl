from xdsl.dialects import linalg, memref_stream
from xdsl.dialects.builtin import (
    ArrayAttr,
    IntAttr,
    ModuleOp,
)
from xdsl.ir import MLContext
from xdsl.passes import ModulePass
from xdsl.pattern_rewriter import (
    PatternRewriter,
    PatternRewriteWalker,
    RewritePattern,
    op_type_rewrite_pattern,
)


class ConvertGenericOpPattern(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: linalg.Generic, rewriter: PatternRewriter) -> None:
        if op.res:
            raise NotImplementedError(
                "converting linalg.generic with results not supported"
            )

        # The memref_stream.generic op may take as arguments memrefs, scalars, or streams,
        # the latter of which does not carry shape information. linalg.generic constructs
        # the nested loop bounds from the shapes of the inputs, so we need to cache that
        # derived information here, as we may not be able to recover it later.
        ubs = op.get_static_loop_ranges()
        bounds = ArrayAttr(IntAttr(ub) for ub in ubs)

        rewriter.replace_matched_op(
            memref_stream.GenericOp(
                op.inputs,
                op.outputs,
                rewriter.move_region_contents_to_new_regions(op.body),
                op.indexing_maps,
                op.iterator_types,
                bounds,
            )
        )


class ConvertLinalgToMemrefStreamPass(ModulePass):
    name = "convert-linalg-to-memref-stream"

    def apply(self, ctx: MLContext, op: ModuleOp) -> None:
        PatternRewriteWalker(
            ConvertGenericOpPattern(),
            apply_recursively=False,
        ).rewrite_module(op)
