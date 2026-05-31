type StoredVideoFrame = {
	bytes: ArrayBuffer;
	mimeType: string;
	expiresAt: number;
};

const frames = new Map<string, StoredVideoFrame>();
const FRAME_TTL_MS = 15 * 60 * 1000;

function pruneExpiredFrames() {
	const now = Date.now();
	for (const [id, frame] of frames) {
		if (frame.expiresAt <= now) frames.delete(id);
	}
}

export function storeVideoFrame(bytes: Uint8Array, mimeType: string): string {
	pruneExpiredFrames();
	const id = crypto.randomUUID();
	const copy = new Uint8Array(bytes.byteLength);
	copy.set(bytes);
	frames.set(id, {
		bytes: copy.buffer,
		mimeType,
		expiresAt: Date.now() + FRAME_TTL_MS
	});
	return id;
}

export function getVideoFrame(id: string): StoredVideoFrame | null {
	pruneExpiredFrames();
	const frame = frames.get(id);
	if (!frame) return null;
	return frame;
}
