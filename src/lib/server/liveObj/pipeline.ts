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

function resolveRawPostExecutorScript(): string {
	const env = process.env.RAW_OBJ_POST_EXECUTOR_PATH;
	if (env) return env;
	return path.join(process.cwd(), 'src/routes/api/executor/raw_obj_post_executor.py');
}

function resolveDreamRebuildExecutorScript(): string {
	const env = process.env.DREAM_REBUILD_EXECUTOR_PATH;
	if (env) return env;
	return path.join(process.cwd(), 'src/routes/api/executor/dream_rebuild_reconstruct.py');
}

function resolveUvDreamEnhanceScript(): string {
	const env = process.env.UV_DREAM_ENHANCE_SCRIPT;
	if (env) return env;
	return path.join(process.cwd(), 'scripts/uv_dream_enhance.py');
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

async function runPythonOnFile(
	script: string,
	inputPath: string,
	outputPath: string
): Promise<string> {
	return runPythonArgs(script, [inputPath, '-o', outputPath]);
}

async function runPythonArgs(script: string, args: string[]): Promise<string> {
	const tried = pythonInterpreterCandidates();
	let lastEnoent: unknown;
	for (const cmd of tried) {
		try {
			const { stderr } = await execFileAsync(cmd, [script, ...args], {
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
		lastEnoent instanceof Error ? lastEnoent.message : lastEnoent != null ? String(lastEnoent) : '';
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

/**
 * Run `raw_obj_post_executor.py` on raw LLM OBJ text; returns the OBJ with the
 * `#@post:` modifier stack applied. This is separate from the Live OBJ executor
 * so raw-first experiments do not change metadata-driven execution semantics.
 */
export async function expandRawObjWithPostExecutor(rawObjText: string): Promise<ExecutorResult> {
	const script = resolveRawPostExecutorScript();
	const dir = await mkdtemp(path.join(tmpdir(), 'raw-obj-post-'));
	const inputPath = path.join(dir, 'scene.obj');
	const outputPath = path.join(dir, 'scene.post.obj');
	try {
		await writeFile(inputPath, rawObjText, 'utf-8');
		const stderr = await runPythonOnFile(script, inputPath, outputPath);
		const executedObj = await readFile(outputPath, 'utf-8');
		return { executedObj, warnings: parseExecutorWarnings(stderr) };
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
}

export type DreamRebuildExecutorInput = {
	liveObj: string;
	targetObjectId: string;
	resolution?: number;
	profile?: string;
	mode?: string;
	viewMasks: Record<string, { width: number; height: number; rows: string[] }>;
	viewDepthMaps?: Record<string, { width: number; height: number; rows: string[] }>;
};

export async function reconstructDreamRebuildWithExecutor(
	input: DreamRebuildExecutorInput
): Promise<ExecutorResult> {
	const script = resolveDreamRebuildExecutorScript();
	const dir = await mkdtemp(path.join(tmpdir(), 'dream-rebuild-'));
	const inputPath = path.join(dir, 'dream.json');
	const outputPath = path.join(dir, 'scene.dream.obj');
	try {
		await writeFile(inputPath, JSON.stringify(input), 'utf-8');
		const stderr = await runPythonOnFile(script, inputPath, outputPath);
		const executedObj = await readFile(outputPath, 'utf-8');
		return { executedObj, warnings: parseExecutorWarnings(stderr) };
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
}

export type UvDreamUnwrapResult = {
	sourceUvPng: Uint8Array;
	sourceGuidePng: Uint8Array;
	warnings: string[];
};

export async function unwrapUvDreamSource(input: {
	liveObj: string;
	targetObjectId: string;
}): Promise<UvDreamUnwrapResult> {
	const script = resolveUvDreamEnhanceScript();
	const dir = await mkdtemp(path.join(tmpdir(), 'uv-dream-unwrap-'));
	const inputPath = path.join(dir, 'scene.obj');
	const sourceUvPath = path.join(dir, 'source-uv.png');
	const sourceGuidePath = path.join(dir, 'source-guide.png');
	try {
		await writeFile(inputPath, input.liveObj, 'utf-8');
		const stderr = await runPythonArgs(script, [
			inputPath,
			'--target',
			input.targetObjectId,
			'--source-guide-out',
			sourceGuidePath,
			'--debug-source-uv-out',
			sourceUvPath
		]);
		return {
			sourceUvPng: new Uint8Array(await readFile(sourceUvPath)),
			sourceGuidePng: new Uint8Array(await readFile(sourceGuidePath)),
			warnings: parseExecutorWarnings(stderr)
		};
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
}

export type UvDreamEnhanceResult = ExecutorResult & {
	artifacts: {
		sourceUvPng: Uint8Array;
		finalUvPng: Uint8Array;
		heightPng: Uint8Array;
		diffusePng: Uint8Array;
		manifestJson: string;
	};
};

export async function enhanceUvDreamWithExecutor(input: {
	liveObj: string;
	targetObjectId: string;
	heightBmp: Uint8Array;
	diffuseBmp?: Uint8Array;
	amount?: number;
	shade?: 'smooth' | 'flat';
	mode?: 'displace' | 'map-remesh';
}): Promise<UvDreamEnhanceResult> {
	const script = resolveUvDreamEnhanceScript();
	const dir = await mkdtemp(path.join(tmpdir(), 'uv-dream-enhance-'));
	const inputPath = path.join(dir, 'scene.obj');
	const heightPath = path.join(dir, 'height.bmp');
	const inputDiffusePath = path.join(dir, 'generated-diffuse.bmp');
	const outputPath = path.join(dir, 'scene.uv-dream.obj');
	const sourceUvPath = path.join(dir, 'source-uv.png');
	const finalUvPath = path.join(dir, 'final-uv.png');
	const processedHeightPath = path.join(dir, 'height-tile.png');
	const diffusePath = path.join(dir, 'diffuse.png');
	const manifestPath = path.join(dir, 'manifest.json');
	try {
		await writeFile(inputPath, input.liveObj, 'utf-8');
		await writeFile(heightPath, input.heightBmp);
		if (input.diffuseBmp) await writeFile(inputDiffusePath, input.diffuseBmp);
		const args = [
			inputPath,
			'--target',
			input.targetObjectId,
			'--height-bmp',
			heightPath,
			'--out',
			outputPath,
			'--debug-source-uv-out',
			sourceUvPath,
			'--debug-final-uv-out',
			finalUvPath,
			'--processed-height-out',
			processedHeightPath,
			'--diffuse-out',
			diffusePath,
			'--manifest-out',
			manifestPath,
			'--mode',
			input.mode ?? 'displace',
			'--amount',
			String(input.amount ?? 1),
			'--shade',
			input.shade ?? 'smooth'
		];
		if (input.diffuseBmp) args.push('--input-diffuse-bmp', inputDiffusePath);
		const stderr = await runPythonArgs(script, args);
		return {
			executedObj: await readFile(outputPath, 'utf-8'),
			warnings: parseExecutorWarnings(stderr),
			artifacts: {
				sourceUvPng: new Uint8Array(await readFile(sourceUvPath)),
				finalUvPng: new Uint8Array(await readFile(finalUvPath)),
				heightPng: new Uint8Array(await readFile(processedHeightPath)),
				diffusePng: new Uint8Array(await readFile(diffusePath)),
				manifestJson: await readFile(manifestPath, 'utf-8')
			}
		};
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
}
