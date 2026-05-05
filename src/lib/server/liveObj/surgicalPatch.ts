import { parseStructuredJson } from '$lib/server/llm/chat';

export type LiveObjTextEdit = {
	find: string;
	replace: string;
};

export type LiveObjSurgicalPatch = {
	summary?: string;
	edits: LiveObjTextEdit[];
};

export type AppliedLiveObjPatch = {
	liveObj: string;
	appliedEdits: number;
	summary?: string;
};

function assertString(value: unknown, label: string): string {
	if (typeof value !== 'string')
		throw new Error(`Invalid surgical patch: ${label} must be a string`);
	return value;
}

export function parseLiveObjSurgicalPatch(content: string): LiveObjSurgicalPatch {
	const parsed = parseStructuredJson<unknown>(content);
	if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
		throw new Error('Invalid surgical patch: expected a JSON object');
	}
	const candidate = parsed as { summary?: unknown; edits?: unknown };
	if (!Array.isArray(candidate.edits)) {
		throw new Error('Invalid surgical patch: edits must be an array');
	}
	const edits = candidate.edits.map((edit, index) => {
		if (!edit || typeof edit !== 'object' || Array.isArray(edit)) {
			throw new Error(`Invalid surgical patch: edit ${index + 1} must be an object`);
		}
		const e = edit as { find?: unknown; replace?: unknown };
		const find = assertString(e.find, `edit ${index + 1}.find`);
		const replace = assertString(e.replace, `edit ${index + 1}.replace`);
		if (!find) throw new Error(`Invalid surgical patch: edit ${index + 1}.find cannot be empty`);
		return { find, replace };
	});
	if (edits.length === 0) throw new Error('Invalid surgical patch: edits cannot be empty');
	const summary =
		typeof candidate.summary === 'string' && candidate.summary.trim()
			? candidate.summary.trim()
			: undefined;
	return { summary, edits };
}

function occurrenceCount(haystack: string, needle: string): number {
	let count = 0;
	let offset = 0;
	while (offset <= haystack.length) {
		const index = haystack.indexOf(needle, offset);
		if (index < 0) return count;
		count += 1;
		offset = index + needle.length;
	}
	return count;
}

export function applyLiveObjSurgicalPatch(
	currentLiveObj: string,
	patch: LiveObjSurgicalPatch
): AppliedLiveObjPatch {
	let next = currentLiveObj;
	for (const [index, edit] of patch.edits.entries()) {
		const matches = occurrenceCount(next, edit.find);
		if (matches === 0) {
			throw new Error(`Surgical edit ${index + 1} did not match the current Live OBJ`);
		}
		if (matches > 1) {
			throw new Error(
				`Surgical edit ${index + 1} matched ${matches} locations; target must be unique`
			);
		}
		next = next.replace(edit.find, edit.replace);
	}
	if (next.trim() && !next.endsWith('\n')) next += '\n';
	return {
		liveObj: next,
		appliedEdits: patch.edits.length,
		summary: patch.summary
	};
}
