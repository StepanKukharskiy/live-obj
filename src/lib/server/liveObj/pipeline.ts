import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

const execFileAsync = promisify(execFile);

export { stripCodeFences } from '$lib/liveObj/stripCodeFences';

function resolveExecutorScript(): string {
	const env = process.env.LIVE_OBJ_EXECUTOR_PATH;
	if (env) return env;
	return path.join(process.cwd(), 'src/routes/api/executor/live_obj_executor_v02.py');
}

/** Interpreters to try, in order. GUI-launched Node often has no PATH entry for python3 — use absolute fallbacks. */
function pythonInterpreterCandidates(): string[] {
	const fromEnv = process.env.LIVE_OBJ_PYTHON?.trim();
	const out: string[] = [];
	if (fromEnv) out.push(fromEnv);
	out.push('python3', 'python');
	if (process.platform === 'darwin') {
		out.push('/usr/bin/python3', '/opt/homebrew/bin/python3', '/usr/local/bin/python3');
	} else if (process.platform !== 'win32') {
		out.push('/usr/bin/python3');
	}
	return [...new Set(out)];
}

/** Only retry the next interpreter when the binary itself could not be spawned (missing from PATH / disk). */
function isExecutableNotFound(e: unknown): boolean {
	if (!e || typeof e !== 'object') return false;
	const code = (e as NodeJS.ErrnoException).code;
	return code === 'ENOENT';
}

function formatExecFailureMessage(cmd: string, err: unknown): string {
	let hint = '';
	if (err instanceof Error) {
		hint = err.message;
		const se = (err as Error & { stderr?: Buffer }).stderr;
		if (se != null && se.length > 0) hint += `\n${se.toString().trim()}`;
	} else {
		hint = String(err);
	}
	return `Python executor failed (interpreter: ${cmd}). ${hint}`.trim();
}

async function probeCadQuery(cmd: string): Promise<string> {
	try {
		const { stdout } = await execFileAsync(cmd, [
			'-c',
			'import importlib.util; import sys; s=importlib.util.find_spec("cadquery"); print(sys.executable); print("cadquery=" + ("yes" if s else "no"))'
		]);
		return stdout.trim();
	} catch (e) {
		if (isExecutableNotFound(e)) return `interpreter not found: ${cmd}`;
		return `probe failed: ${e instanceof Error ? e.message : String(e)}`;
	}
}

async function runPythonOnFile(script: string, inputPath: string, outputPath: string): Promise<string> {
	const args = [script, inputPath, '-o', outputPath];
	const tried = pythonInterpreterCandidates();
	let lastEnoent: unknown;
	for (const cmd of tried) {
		try {
			const { stderr } = await execFileAsync(cmd, args, {
				timeout: 120_000,
				maxBuffer: 32 * 1024 * 1024
			});
			return stderr ?? '';
		} catch (e) {
			if (isExecutableNotFound(e)) {
				lastEnoent = e;
				continue;
			}
			const cadQueryProbe = await probeCadQuery(cmd);
			throw new Error(`${formatExecFailureMessage(cmd, e)}\nCadQuery probe:\n${cadQueryProbe}`);
		}
	}
	const tail =
		lastEnoent instanceof Error
			? lastEnoent.message
			: lastEnoent != null
				? String(lastEnoent)
				: '';
	throw new Error(
		`No Python interpreter found (tried: ${tried.join(', ')}). Set LIVE_OBJ_PYTHON to your python3 executable; LIVE_OBJ_EXECUTOR_PATH only sets the script path. ${tail}`.trim()
	);
}

export type ExecutorResult = {
	executedObj: string;
	/** Non-fatal diagnostics collected from the executor's stderr (one per line). */
	warnings: string[];
};

/** Extract meaningful warning lines from the executor's stderr. Drops blank lines and tracebacks. */
function parseExecutorWarnings(stderr: string): string[] {
	if (!stderr) return [];
	return stderr
		.split('\n')
		.map((l) => l.trim())
		.filter((l) => l.length > 0 && !l.startsWith('Traceback') && !l.startsWith('  File "'));
}

/**
 * Run `live_obj_executor_v02.py` on the Live OBJ text; returns the serialized scene with v/f
 * updated plus any non-fatal warnings the executor emitted on stderr.
 */
export async function expandLiveObjWithExecutor(liveObjText: string): Promise<ExecutorResult> {
	const script = resolveExecutorScript();
	const dir = await mkdtemp(path.join(tmpdir(), 'live-obj-'));
	const inputPath = path.join(dir, 'scene.obj');
	const outputPath = path.join(dir, 'scene.executed.obj');
	try {
		await writeFile(inputPath, liveObjText, 'utf-8');
		const stderr = await runPythonOnFile(script, inputPath, outputPath);
		const executedObj = await readFile(outputPath, 'utf-8');
		return { executedObj, warnings: parseExecutorWarnings(stderr) };
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
}
