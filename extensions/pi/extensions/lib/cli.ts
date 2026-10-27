import { resolve } from "node:path";

export type PiExecResult = {
	stdout: string;
	stderr: string;
	code: number;
	killed: boolean;
};

export type PiExec = (
	command: string,
	args: string[],
	options?: { cwd?: string; timeout?: number },
) => Promise<PiExecResult>;

export async function runMelleaSkills(
	exec: PiExec,
	cli: string,
	subcommand: string,
	args: string[],
	options?: { cwd?: string },
): Promise<PiExecResult> {
	return exec(cli, [subcommand, ...args], options);
}

/** Makes a leading positional path absolute, so it survives a change of cwd. */
export function resolveLeadingPath(tokens: string[], userCwd: string): string[] {
	if (tokens.length === 0 || tokens[0].startsWith("-")) return tokens;
	return [resolve(userCwd, tokens[0]), ...tokens.slice(1)];
}

/**
 * Builds `mellea-skills compile` argv for a pi session: the spec path is made
 * absolute (compile runs from the managed clone, not the user's folder), and
 * the backend defaults to pi using the session's own provider and model.
 * Flags the user passed always win. A lone --provider or --model is only
 * completed from the session when it matches it; otherwise this throws.
 */
export function buildCompileArgv(
	tokens: string[],
	userCwd: string,
	model?: { provider: string; id: string },
): string[] {
	const argv = resolveLeadingPath(tokens, userCwd);
	const backend = flagValue(argv, ["--backend", "-b"]);
	if (backend === undefined) argv.push("--backend", "pi");
	if ((backend ?? "pi") !== "pi" || !model) return argv;
	const provider = flagValue(argv, ["--provider"]);
	const modelId = flagValue(argv, ["--model", "-m"]);
	// Fill in only the half that pairs with the other: the session's model
	// belongs to the session's provider, so it can't complete any other one.
	if (provider !== undefined && modelId === undefined) {
		if (provider !== model.provider) {
			throw new Error(
				`--provider ${provider} needs --model too: this session's model (${model.id}) belongs to ${model.provider}.`,
			);
		}
		argv.push("--model", model.id);
	} else if (modelId !== undefined && provider === undefined) {
		if (modelId !== model.id) {
			throw new Error(
				`--model ${modelId} needs --provider too: only this session's model (${model.id}) can be paired with its provider.`,
			);
		}
		argv.push("--provider", model.provider);
	} else if (provider === undefined) {
		argv.push("--provider", model.provider, "--model", model.id);
	}
	return argv;
}

function flagValue(argv: string[], names: string[]): string | undefined {
	for (let i = 0; i < argv.length; i++) {
		for (const name of names) {
			if (argv[i] === name) return argv[i + 1] ?? "";
			if (argv[i].startsWith(`${name}=`)) return argv[i].slice(name.length + 1);
		}
	}
	return undefined;
}

/**
 * Splits a command-line-style string into argv tokens, honoring "..." and
 * '...' as grouping (quotes are stripped from the resulting token; a
 * mismatched/unterminated quote is treated as running to the end of the
 * string rather than throwing). This is NOT a full shell parser — no
 * backslash escapes, no nested quotes — just enough to let a flag value
 * containing spaces (e.g. --input "some text") survive as one token.
 */
export function tokenizeArgs(input: string): string[] {
	const tokens: string[] = [];
	let current = "";
	let quote: '"' | "'" | null = null;

	for (const char of input) {
		if (quote) {
			if (char === quote) {
				quote = null;
			} else {
				current += char;
			}
		} else if (char === '"' || char === "'") {
			quote = char;
		} else if (/\s/.test(char)) {
			if (current) {
				tokens.push(current);
				current = "";
			}
		} else {
			current += char;
		}
	}

	if (current) {
		tokens.push(current);
	}

	return tokens;
}
