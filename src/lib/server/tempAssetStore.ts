type StoredTempAsset = {
	bytes: ArrayBuffer;
	mimeType: string;
	filename?: string;
	expiresAt: number;
};

const assets = new Map<string, StoredTempAsset>();
const TEMP_ASSET_TTL_MS = 15 * 60 * 1000;

function pruneExpiredAssets() {
	const now = Date.now();
	for (const [id, asset] of assets) {
		if (asset.expiresAt <= now) assets.delete(id);
	}
}

export function storeTempAsset(bytes: Uint8Array, mimeType: string, filename?: string): string {
	pruneExpiredAssets();
	const id = crypto.randomUUID();
	const copy = new Uint8Array(bytes.byteLength);
	copy.set(bytes);
	assets.set(id, {
		bytes: copy.buffer,
		mimeType,
		filename,
		expiresAt: Date.now() + TEMP_ASSET_TTL_MS
	});
	return id;
}

export function getTempAsset(id: string): StoredTempAsset | null {
	pruneExpiredAssets();
	return assets.get(id) ?? null;
}
