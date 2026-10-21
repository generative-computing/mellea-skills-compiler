import { homedir } from "node:os";
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { ensureCompiler } from "./lib/bootstrap.js";
import { buildCompileArgv, resolveLeadingPath, runMelleaSkills, tokenizeArgs } from "./lib/cli.js";

type CommandSpec = {
	name: string;
	subcommand: string;
	description: string;
	usage: string;
	status: string;
	label: string;
};

const COMMANDS: CommandSpec[] = [
	{
		name: "mellea-compile",
		subcommand: "compile",
		description: "Compile a Mellea skill specification (.md) into a typed pipeline",
		usage:
			"Usage: /mellea-compile <path-to-spec.md> [flags...] — compiles with this session's provider and model unless you pass --backend/--provider/--model",
		status: "Compiling...",
		label: "Compile",
	},
	{
		name: "mellea-certify",
		subcommand: "certify",
		description: "Run the full certification pipeline on a compiled Mellea skill",
		usage:
			"Usage: /mellea-certify <compiled-skill-dir> [--enforce] [-n N] [--inference-engine ollama|vllm] [--risk-model ...] [--guardian-model ...]",
		status: "Certifying...",
		label: "Certify",
	},
	{
		name: "mellea-validate",
		subcommand: "validate",
		description: "Validate a compiled Mellea skill (lints + fixture smoke-check)",
		usage: "Usage: /mellea-validate <compiled-skill-dir> [--no-run] [--all]",
		status: "Validating...",
		label: "Validate",
	},
	{
		name: "mellea-run",
		subcommand: "run",
		description: "Run a compiled Mellea skill pipeline against an input",
		usage:
			"Usage: /mellea-run <compiled-skill-dir> [--fixture ...] [--input ...] [--enforce] [--no-guardian] [--inference-engine ollama|vllm]",
		status: "Running...",
		label: "Run",
	},
];

export default function melleaSkillsExtension(pi: ExtensionAPI) {
	for (const spec of COMMANDS) {
		pi.registerCommand(spec.name, {
			description: spec.description,
			handler: (args: string, ctx: ExtensionCommandContext) => runCommand(pi, spec, args, ctx),
		});
	}
}

async function runCommand(pi: ExtensionAPI, spec: CommandSpec, args: string, ctx: ExtensionCommandContext) {
	const tokens = tokenizeArgs(args.trim());
	if (tokens.length === 0) {
		ctx.ui.notify(spec.usage, "warning");
		return;
	}

	let install;
	ctx.ui.setStatus("mellea-skills", "Setting up compiler...");
	try {
		install = await ensureCompiler(pi.exec, (message, level) => ctx.ui.notify(message, level ?? "info"), {
			home: homedir(),
		});
	} catch (err) {
		ctx.ui.notify(err instanceof Error ? err.message : String(err), "error");
		return;
	} finally {
		ctx.ui.setStatus("mellea-skills", undefined);
	}

	// compile must run from the managed clone, where the compile agent finds
	// its instructions; the other commands run from the user's folder.
	const isCompile = spec.subcommand === "compile";
	const argv = isCompile ? buildCompileArgv(tokens, ctx.cwd, ctx.model) : resolveLeadingPath(tokens, ctx.cwd);
	const cwd = isCompile ? install.repoDir : ctx.cwd;

	ctx.ui.setStatus("mellea-skills", spec.status);
	try {
		const result = await runMelleaSkills(pi.exec, install.cli, spec.subcommand, argv, { cwd });
		if (result.code === 0) {
			ctx.ui.notify(result.stdout || result.stderr || `${spec.label} succeeded.`, "info");
		} else {
			ctx.ui.notify(result.stderr || `${spec.label} failed (exit ${result.code}).`, "error");
		}
	} finally {
		ctx.ui.setStatus("mellea-skills", undefined);
	}
}
