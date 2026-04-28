import adapter from '@sveltejs/adapter-node';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		// Runes for app code; legacy for Canvas3D (large, still on export let + $:).
		runes: ({ filename }) => {
			const f = filename.replace(/\\/g, '/');
			if (f.split('/').includes('node_modules')) return undefined;
			if (f.endsWith('Canvas3D.svelte')) return false;
			return true;
		}
	},
	kit: { adapter: adapter() }
};

export default config;
