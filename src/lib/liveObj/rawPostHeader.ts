const LIVE_SOURCE_RE = /#@source:\s*(procedural|assembly|sdf|simulation|recipe)/i;

export function hasProceduralLiveSources(sourceText: string): boolean {
	return LIVE_SOURCE_RE.test(sourceText);
}

function hasHeaderLine(sourceText: string, key: string): boolean {
	return new RegExp(`^\\s*#@${key}(?::|\\b)`, 'im').test(sourceText);
}

export function normalizeRawPostHeader(
	sourceText: string,
	options: { sourcePrompt?: string } = {}
): string {
	const text = String(sourceText ?? '').trim();
	if (!text || hasProceduralLiveSources(text)) return sourceText;

	const additions: string[] = [];
	if (!hasHeaderLine(text, 'scene')) additions.push('#@scene');
	if (!hasHeaderLine(text, 'live_obj_version')) additions.push('#@live_obj_version: 0.1');
	if (!hasHeaderLine(text, 'workflow')) additions.push('#@workflow: raw_post');
	if (!hasHeaderLine(text, 'up')) additions.push('#@up: y');
	if (options.sourcePrompt?.trim() && !hasHeaderLine(text, 'source_prompt')) {
		additions.push(`#@source_prompt: ${JSON.stringify(options.sourcePrompt.trim())}`);
	}

	const normalized = additions.length > 0 ? `${additions.join('\n')}\n${text}` : text;
	return `${normalized}\n`;
}
