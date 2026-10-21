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

test("explicit -b pi and -m are respected", () => {
	assert.deepEqual(buildCompileArgv(["spec.md", "-b", "pi", "-m", "glm-5.3"], "/u", sonnet), [
		"/u/spec.md",
		"-b",
		"pi",
		"-m",
		"glm-5.3",
		"--provider",
		"anthropic",
	]);
});

test("explicit --provider is respected", () => {
	assert.deepEqual(buildCompileArgv(["spec.md", "--provider", "ollama"], "/u", sonnet), [
		"/u/spec.md",
		"--provider",
		"ollama",
		"--backend",
		"pi",
		"--model",
		"claude-sonnet-5-5",
	]);
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
