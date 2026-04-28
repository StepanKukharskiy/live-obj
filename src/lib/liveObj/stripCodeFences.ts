/**
 * Prefer the inner body of the first markdown ```fence``` anywhere in the text.
 * (Keeps parity with server `liveObj/pipeline.ts` for `/api/live-obj/execute`.)
 */
export function stripCodeFences(text: string): string {
	const t = text.trim();
	if (!t) return t;
	const firstFence =
		/```(?:[a-zA-Z0-9_-]+)?\s*\r?\n([\s\S]*?)```/.exec(t) ?? /```([\s\S]*?)```/.exec(t);
	if (firstFence?.[1] != null) {
		const inner = firstFence[1].trim();
		if (inner.length > 0) return inner;
	}
	return t;
}
