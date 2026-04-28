/**
 * Drops OBJ geometry lines while keeping `#` comments (#@ metadata), objects, groups,
 * and material directives — useful when v/f overwhelm the editor.
 */
export function stripLiveObjMeshLines(text: string): string {
	const lines = text.split(/\r?\n/);
	const kept: string[] = [];
	let lastBlankRun = false;
	for (const line of lines) {
		const t = line.trim();
		if (t === '') {
			if (!lastBlankRun && kept.length > 0) {
				kept.push('');
				lastBlankRun = true;
			}
			continue;
		}
		lastBlankRun = false;
		if (t.startsWith('#')) {
			kept.push(line);
			continue;
		}
		const ft = /^(\S+)/.exec(t)?.[1]?.toLowerCase();
		if (
			ft === 'v' ||
			ft === 'vn' ||
			ft === 'vt' ||
			ft === 'vp' ||
			ft === 'f' ||
			ft === 'fo' ||
			ft === 'l'
		) {
			continue;
		}
		kept.push(line);
	}
	while (kept.length && kept[kept.length - 1] === '') kept.pop();
	return kept.join('\n');
}
