import { readFile } from 'node:fs/promises';
import { extname, relative, resolve, sep } from 'node:path';
import type { RequestHandler } from './$types';

const PROJECT_FILE_ROOT = resolve(process.cwd(), 'project_live_obj_files');

const MIME_TYPES: Record<string, string> = {
	'.bmp': 'image/bmp',
	'.gif': 'image/gif',
	'.jpg': 'image/jpeg',
	'.jpeg': 'image/jpeg',
	'.json': 'application/json',
	'.obj': 'text/plain; charset=utf-8',
	'.png': 'image/png',
	'.webp': 'image/webp'
};

function isInsideProjectFiles(path: string): boolean {
	const rel = relative(PROJECT_FILE_ROOT, path);
	return rel === '' || (!rel.startsWith('..') && !rel.startsWith(sep));
}

export const GET: RequestHandler = async ({ url }) => {
	const requestedPath = url.searchParams.get('path');
	if (!requestedPath) return new Response('Missing path', { status: 400 });

	const resolvedPath = resolve(process.cwd(), requestedPath);
	if (!isInsideProjectFiles(resolvedPath)) {
		return new Response('Forbidden', { status: 403 });
	}

	try {
		const file = await readFile(resolvedPath);
		const type = MIME_TYPES[extname(resolvedPath).toLowerCase()] ?? 'application/octet-stream';
		return new Response(file, {
			headers: {
				'Cache-Control': 'no-store',
				'Content-Type': type
			}
		});
	} catch {
		return new Response('Not found', { status: 404 });
	}
};
