export type PiExecResult = {
	stdout: string;
	stderr: string;
	code: number;
	killed: boolean;
};

export type PiExec = (
	command: string,
	args: string[],
	options?: { cwd?: string },
) => Promise<PiExecResult>;

export const CLI_MISSING_MESSAGE =
	"mellea-skills CLI not found on PATH. Install it first — see " +
	"https://github.com/generative-computing/mellea-skills-compiler#install " +
	"(pip install -e . from a clone of the repo).";

export async function checkCliAvailable(exec: PiExec): Promise<boolean> {
	const result = await exec("mellea-skills", ["version"]);
	return result.code === 0;
}

export async function runMelleaSkills(
	exec: PiExec,
	subcommand: string,
	args: string[],
	options?: { cwd?: string },
): Promise<PiExecResult> {
	return exec("mellea-skills", [subcommand, ...args], options);
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
