// RETURN — merges the validated AI output into the package and hands it back to the main workflow.
const { result, ctx, provider, attempt } = $input.first().json;
const pkg = JSON.parse(JSON.stringify(ctx.pkg));
pkg[ctx.stage] = result;
pkg.llm_log = [...(pkg.llm_log ?? []), { stage: ctx.stage, provider, attempt: attempt + 1, at: new Date().toISOString() }];
return [{ json: { pkg } }];
