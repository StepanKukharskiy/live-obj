import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

const execFileAsync = promisify(execFile);

export function stripCodeFences(text: string): string {
	let t = text.trim();
	const fence = /^```(?:[a-zA-Z0-9_-]+)?\s*\n?([\s\S]*?)```$/m;
	const m = t.match(fence);
	if (m) t = m[1].trim();
	return t;
}

function resolveExecutorScript(): string {
	const env = process.env.LIVE_OBJ_EXECUTOR_PATH;
	if (env) return env;
	return path.join(process.cwd(), 'src/routes/api/executor/live_obj_executor_v02.py');
}

async function runPythonOnFile(script: string, inputPath: string, outputPath: string): Promise<void> {
	const args = [script, inputPath, '-o', outputPath];
	for (const cmd of ['python3', 'python'] as const) {
		try {
			await execFileAsync(cmd, args, { timeout: 120_000, maxBuffer: 32 * 1024 * 1024 });
			return;
		} catch {
			/* try next */
		}
	}
	throw new Error('Python executor failed (tried python3 and python; set LIVE_OBJ_EXECUTOR_PATH if needed)');
}

/**
 * Run `live_obj_executor_v02.py` on the Live OBJ text; returns the serialized scene with v/f updated.
 */
export async function expandLiveObjWithExecutor(liveObjText: string): Promise<string> {
	const script = resolveExecutorScript();
	const dir = await mkdtemp(path.join(tmpdir(), 'live-obj-'));
	const inputPath = path.join(dir, 'scene.obj');
	const outputPath = path.join(dir, 'scene.executed.obj');
	try {
		await writeFile(inputPath, liveObjText, 'utf-8');
		await runPythonOnFile(script, inputPath, outputPath);
		return await readFile(outputPath, 'utf-8');
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
}
