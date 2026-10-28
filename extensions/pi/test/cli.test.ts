import { test } from "node:test";
import assert from "node:assert/strict";
import { buildCompileArgv, tokenizeArgs } from "../extensions/lib/cli.ts";

const sonnet = { provider: "anthropic", id: "claude-sonnet-5-5" };

test("defaults to pi backend with session provider and model", () => {
	assert.deepEqual(buildCompileArgv(["skills/w/spec.md"], "/u", sonnet), [
		"/u/skills/w/spec.md",
		"--backend",
		"pi",
		"--provider",
		"anthropic",
		"--model",
		"claude-sonnet-5-5",
	]);
});

test("explicit --backend claude is kept and gets no provider", () => {
	assert.deepEqual(buildCompileArgv(["spec.md", "--backend", "claude"], "/u", sonnet), [
		"/u/spec.md",
		"--backend",
		"claude",
	]);
});

test("explicit -b pi, --provider and -m are respected", () => {
	assert.deepEqual(
		buildCompileArgv(["spec.md", "-b", "pi", "--provider", "zai", "-m", "glm-5.3"], "/u", sonnet),
		["/u/spec.md", "-b", "pi", "--provider", "zai", "-m", "glm-5.3"],
	);
});

test("--provider matching the session gets the session model", () => {
	assert.deepEqual(buildCompileArgv(["spec.md", "--provider", "anthropic"], "/u", sonnet), [
		"/u/spec.md",
		"--provider",
		"anthropic",
		"--backend",
		"pi",
		"--model",
		"claude-sonnet-5-5",
	]);
});

test("--provider for another provider without --model is refused", () => {
	assert.throws(
		() => buildCompileArgv(["spec.md", "--provider", "ollama"], "/u", sonnet),
		/--provider ollama.*--model/,
	);
});

test("--model matching the session gets the session provider", () => {
	assert.deepEqual(buildCompileArgv(["spec.md", "-m", "claude-sonnet-5-5"], "/u", sonnet), [
		"/u/spec.md",
		"-m",
		"claude-sonnet-5-5",
		"--backend",
		"pi",
		"--provider",
		"anthropic",
	]);
});

test("--model for another model without --provider is refused", () => {
	assert.throws(() => buildCompileArgv(["spec.md", "-m", "glm-5.3"], "/u", sonnet), /--model glm-5.3.*--provider/);
});

test("--provider without --model is passed through when there is no session model", () => {
	assert.deepEqual(buildCompileArgv(["spec.md", "--provider", "ollama"], "/u", undefined), [
		"/u/spec.md",
		"--provider",
		"ollama",
		"--backend",
		"pi",
	]);
});

test("--provider=value and --model=value forms are refused the same way", () => {
	assert.throws(() => buildCompileArgv(["spec.md", "--provider=ollama"], "/u", sonnet), /--provider ollama.*--model/);
	assert.throws(() => buildCompileArgv(["spec.md", "--model=glm-5.3"], "/u", sonnet), /--model glm-5.3.*--provider/);
});

test("--flag=value forms count as explicit", () => {
	assert.deepEqual(buildCompileArgv(["spec.md", "--backend=bob"], "/u", sonnet), ["/u/spec.md", "--backend=bob"]);
});

test("absolute spec path is unchanged", () => {
	assert.equal(buildCompileArgv(["/abs/spec.md"], "/u", sonnet)[0], "/abs/spec.md");
});

test("quoted path with spaces resolves", () => {
	assert.equal(buildCompileArgv(tokenizeArgs('"my skills/spec.md"'), "/u", sonnet)[0], "/u/my skills/spec.md");
});

test("no session model omits provider and model", () => {
	assert.deepEqual(buildCompileArgv(["spec.md"], "/u", undefined), ["/u/spec.md", "--backend", "pi"]);
});
