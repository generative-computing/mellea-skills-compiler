import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { PiExec, PiExecResult } from "./cli.ts";

// Until the compiler is on PyPI with its instruction files packaged, the
// compile agent needs a full checkout (it reads .claude/, .pi/prompts/ and
// docs/dialects/ relative to its working directory).
export const COMPILER_REF = "v0.3.0";
export const COMPILER_REPO = "https://github.com/generative-computing/mellea-skills-compiler.git";

const PYTHON_RANGE = ">=3.11,<3.14.4";
const PYTHON_CANDIDATES = ["python3.13", "python3.12", "python3.11", "python3"];
const SLOW_STEP_TIMEOUT_MS = 600_000;

export type CompilerInstall = { cli: string; repoDir: string };
export type Log = (message: string, level?: "info" | "warning" | "error") => void;

export function installPaths(home: string, ref: string = COMPILER_REF) {
	const root = join(home, ".cache", "mellea-skills-compiler", ref);
	return {
		root,
		repoDir: join(root, "repo"),
		venvDir: join(root, "venv"),
		cli: join(root, "venv", "bin", "mellea-skills"),
		marker: join(root, ".install-complete"),
	};
}

const inFlight = new Map<string, Promise<CompilerInstall>>();

export function ensureCompiler(
	exec: PiExec,
	log: Log,
	opts: { home: string; ref?: string },
): Promise<CompilerInstall> {
	const ref = opts.ref ?? COMPILER_REF;
	const paths = installPaths(opts.home, ref);
	// Two commands started together must not both wipe and rebuild the root.
	const pending = inFlight.get(paths.root);
	if (pending) return pending;
	const install = ensureCompilerOnce(exec, log, ref, paths).finally(() => inFlight.delete(paths.root));
	inFlight.set(paths.root, install);
	return install;
}

async function ensureCompilerOnce(
	exec: PiExec,
	log: Log,
	ref: string,
	paths: ReturnType<typeof installPaths>,
): Promise<CompilerInstall> {
	if (existsSync(paths.marker) && (await isWorkingCli(exec, paths.cli))) {
		return { cli: paths.cli, repoDir: paths.repoDir };
	}

	log(`Setting up the mellea-skills compiler ${ref} (first run only, this can take a few minutes)…`);

	await requireTool(exec, "git", ["--version"], "git is required to download the compiler. Install git and try again.");
	const python = await findPythonToolchain(exec);

	// Build in place: venv scripts and the editable install embed absolute
	// paths, so a venv can't be built elsewhere and moved. The marker is
	// written last, so an interrupted run is rebuilt next time.
	rmSync(paths.root, { recursive: true, force: true });
	mkdirSync(paths.root, { recursive: true });

	try {
		await step(log, `Cloning ${COMPILER_REPO} @ ${ref}`, () =>
			run(exec, "git", ["clone", "--depth", "1", "--branch", ref, COMPILER_REPO, paths.repoDir]),
		);
		await step(log, "Creating Python environment", () => python.createVenv(paths.venvDir));
		await step(log, "Installing mellea-skills (this can take a few minutes)", () =>
			python.installEditable(paths.venvDir, paths.repoDir),
		);
		if (!(await isWorkingCli(exec, paths.cli))) {
			throw new Error(`The compiler was installed but \`${paths.cli} version\` failed. Try again.`);
		}
		writeFileSync(paths.marker, `${ref}\n`);
	} catch (err) {
		rmSync(paths.root, { recursive: true, force: true });
		throw err;
	}

	log(`mellea-skills compiler ready at ${paths.root}`);
	return { cli: paths.cli, repoDir: paths.repoDir };
}

type PythonToolchain = {
	createVenv(venvDir: string): Promise<void>;
	installEditable(venvDir: string, repoDir: string): Promise<void>;
};

async function findPythonToolchain(exec: PiExec): Promise<PythonToolchain> {
	if ((await exec("uv", ["--version"])).code === 0) {
		return {
			createVenv: (venvDir) => run(exec, "uv", ["venv", "--python", PYTHON_RANGE, venvDir]),
			installEditable: (venvDir, repoDir) =>
				run(exec, "uv", ["pip", "install", "--python", join(venvDir, "bin", "python"), "-e", repoDir]),
		};
	}

	for (const candidate of PYTHON_CANDIDATES) {
		const result = await exec(candidate, ["--version"]);
		if (result.code === 0 && isSupportedPython(`${result.stdout} ${result.stderr}`)) {
			return {
				createVenv: (venvDir) => run(exec, candidate, ["-m", "venv", venvDir]),
				installEditable: (venvDir, repoDir) =>
					run(exec, join(venvDir, "bin", "python"), ["-m", "pip", "install", "-e", repoDir]),
			};
		}
	}

	throw new Error(
		"The compiler needs Python 3.11 to 3.14.3, and none was found (tried uv, " +
			`${PYTHON_CANDIDATES.join(", ")}). Install uv (https://docs.astral.sh/uv/) or a supported Python and try again.`,
	);
}

function isSupportedPython(versionOutput: string): boolean {
	const match = versionOutput.match(/Python (\d+)\.(\d+)\.(\d+)/);
	if (!match) return false;
	const [major, minor, patch] = match.slice(1).map(Number);
	if (major !== 3 || minor < 11) return false;
	return minor < 14 || (minor === 14 && patch < 4);
}

async function isWorkingCli(exec: PiExec, cli: string): Promise<boolean> {
	return (await exec(cli, ["version"])).code === 0;
}

async function requireTool(exec: PiExec, command: string, args: string[], message: string): Promise<void> {
	if ((await exec(command, args)).code !== 0) throw new Error(message);
}

async function step(log: Log, label: string, action: () => Promise<void>): Promise<void> {
	log(`${label}…`);
	const started = Date.now();
	await action();
	log(`${label}: done (${Math.round((Date.now() - started) / 1000)}s)`);
}

async function run(exec: PiExec, command: string, args: string[]): Promise<void> {
	const result: PiExecResult = await exec(command, args, { timeout: SLOW_STEP_TIMEOUT_MS });
	if (result.code !== 0) {
		const output = (result.stderr || result.stdout).trim().split("\n").slice(-20).join("\n");
		const reason = result.killed ? "timed out" : `exited with code ${result.code}`;
		throw new Error(`Compiler setup failed: \`${command} ${args.join(" ")}\` ${reason}.\n${output}`);
	}
}
