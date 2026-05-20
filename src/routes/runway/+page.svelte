<script lang="ts">
	import gehryVideo from '$lib/assets/Gehry.mp4';
	import { onMount } from 'svelte';
	import type {
		Camera,
		Mesh,
		PlaneGeometry,
		Scene,
		ShaderMaterial,
		Vector2,
		WebGLRenderer
	} from 'three';

	let menuOpen = $state(false);
	let navLight = $state(false);
	let fluidHost: HTMLDivElement | null = $state(null);
	let triggerFluid: ((strength?: number) => void) | null = null;

	const pointer = {
		x: 0.5,
		y: 0.5
	};

	const fluidVertexShader = `
		varying vec2 vUv;

		void main() {
			vUv = uv;
			gl_Position = vec4(position.xy, 0.0, 1.0);
		}
	`;

	const fluidFragmentShader = `
		precision highp float;

		uniform vec2 u_resolution;
		uniform float u_time;
		uniform float u_morph;
		uniform vec2 u_pointer;
		varying vec2 vUv;

		float smin(float a, float b, float k) {
			float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
			return mix(b, a, h) - k * h * (1.0 - h);
		}

		mat2 rot(float a) {
			float s = sin(a);
			float c = cos(a);
			return mat2(c, -s, s, c);
		}

		float sdTorus(vec3 p, vec2 t) {
			vec2 q = vec2(length(p.xz) - t.x, p.y);
			return length(q) - t.y;
		}

		float sdBox(vec3 p, vec3 b) {
			vec3 q = abs(p) - b;
			return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0);
		}

		float map(vec3 p) {
			vec3 bp = p;
			bp.xy -= (u_pointer - 0.5) * u_morph * 0.9;

			vec3 p1 = bp;
			p1.yz *= rot(u_time * 0.34);
			p1.xz *= rot(u_time * 0.24);
			float d1 = sdTorus(p1, vec2(1.2, 0.3));

			vec3 p2 = bp;
			p2.x += sin(u_time * 0.95) * 2.0;
			p2.y += cos(u_time * 0.72) * 1.5;
			p2.z += sin(u_time * 0.56) * 1.0;
			float d2 = length(p2) - 0.6;

			vec3 p3 = bp;
			p3.x += cos(u_time * 0.64) * 2.2;
			p3.y += sin(u_time * 0.88) * 1.8;
			p3.z += cos(u_time * 1.04) * 1.2;
			float d3 = length(p3) - 0.5;

			vec3 p4 = bp;
			p4.x += sin(u_time * 1.12) * 2.5;
			p4.y += cos(u_time * 0.96) * 1.5;
			p4.z += sin(u_time * 0.72) * 2.0;
			p4.xy *= rot(u_time * 0.64);
			p4.yz *= rot(u_time * 0.56);
			float d4 = sdBox(p4, vec3(0.5));

			vec3 p5 = bp;
			p5.x += cos(u_time * 0.88) * -2.0;
			p5.y += sin(u_time * 1.28) * -1.8;
			p5.z += cos(u_time * 0.64) * -2.0;
			p5.xz *= rot(u_time * 0.88);
			p5.yz *= rot(u_time * 1.04);
			float d5 = sdBox(p5, vec3(0.4));

			float blend = 0.72 + u_morph * 2.4;
			float d = smin(d1, d2, blend);
			d = smin(d, d3, blend);
			d = smin(d, d4, blend);
			d = smin(d, d5, blend);

			d += sin(p.x * 2.0 + u_time) * sin(p.y * 2.0 + u_time) * sin(p.z * 2.0) * 0.045;

			return d;
		}

		vec3 calcNormal(vec3 p) {
			vec2 e = vec2(0.01, 0.0);
			return normalize(vec3(
				map(p + e.xyy) - map(p - e.xyy),
				map(p + e.yxy) - map(p - e.yxy),
				map(p + e.yyx) - map(p - e.yyx)
			));
		}

		void main() {
			vec2 uv = gl_FragCoord.xy / u_resolution.xy;
			uv -= 0.5;
			uv.x *= u_resolution.x / u_resolution.y;

			vec3 ro = vec3(uv * 4.25, -10.0);
			vec3 rd = normalize(vec3(0.0, 0.0, 1.0));

			float t = 0.0;
			vec3 p = ro;

			for (int i = 0; i < 64; i++) {
				p = ro + rd * t;
				float d = map(p);
				if (d < 0.004 || t > 25.0) break;
				t += d;
			}

			float vignette = smoothstep(1.2, 0.05, length(uv));
			vec3 backgroundColor = vec3(0.006, 0.008, 0.065) + vec3(0.0, 0.0, 0.18) * vignette;
			vec3 color = backgroundColor;

			if (t < 25.0) {
				vec3 n = calcNormal(p);
				vec3 viewDir = normalize(-rd);
				float caAmount = 0.1;

				vec3 vR = normalize(viewDir + vec3(caAmount, 0.0, 0.0));
				vec3 vG = viewDir;
				vec3 vB = normalize(viewDir - vec3(caAmount, 0.0, 0.0));

				float fresnelR = pow(1.0 - max(dot(n, vR), 0.0), 2.5);
				float fresnelG = pow(1.0 - max(dot(n, vG), 0.0), 2.5);
				float fresnelB = pow(1.0 - max(dot(n, vB), 0.0), 2.5);
				vec3 fresnelCA = vec3(fresnelR, fresnelG, fresnelB);

				vec3 baseColor = vec3(0.01, 0.03, 0.1);
				vec3 lightDir = normalize(vec3(1.0, 1.0, -1.0));
				float diff = max(dot(n, lightDir), 0.0);
				vec3 objectColor = baseColor + vec3(0.0, 0.4, 0.9) * diff * 0.5;

				vec3 iridescence = 0.5 + 0.5 * cos(u_time + p.y * 2.0 + vec3(0.0, 2.0, 4.0));
				objectColor += fresnelCA * iridescence * 1.55;
				objectColor += vec3(fresnelR * 1.1, 0.0, fresnelB * 1.18);

				vec3 halfR = normalize(lightDir + vR);
				vec3 halfG = normalize(lightDir + vG);
				vec3 halfB = normalize(lightDir + vB);
				float specR = pow(max(dot(n, halfR), 0.0), 64.0);
				float specG = pow(max(dot(n, halfG), 0.0), 64.0);
				float specB = pow(max(dot(n, halfB), 0.0), 64.0);
				objectColor += vec3(specR, specG, specB) * 1.15;
				color = objectColor;
			}

			gl_FragColor = vec4(color, 1.0);
		}
	`;

	onMount(() => {
		const updateNavTheme = () => {
			navLight = window.scrollY > window.innerHeight * 0.82;
		};

		let disposed = false;
		let cleanupFluid: (() => void) | null = null;

		updateNavTheme();
		window.addEventListener('scroll', updateNavTheme, { passive: true });
		window.addEventListener('resize', updateNavTheme);

		void (async () => {
			const THREE = await import('three');
			if (disposed || !fluidHost) return;

			const renderer: WebGLRenderer = new THREE.WebGLRenderer({
				alpha: true,
				antialias: true,
				powerPreference: 'high-performance'
			});
			const scene: Scene = new THREE.Scene();
			const camera: Camera = new THREE.Camera();
			const uniforms: {
				u_resolution: { value: Vector2 };
				u_time: { value: number };
				u_morph: { value: number };
				u_pointer: { value: Vector2 };
			} = {
				u_resolution: { value: new THREE.Vector2(1, 1) },
				u_time: { value: 0 },
				u_morph: { value: 0 },
				u_pointer: { value: new THREE.Vector2(pointer.x, pointer.y) }
			};
			const geometry: PlaneGeometry = new THREE.PlaneGeometry(2, 2);
			const material: ShaderMaterial = new THREE.ShaderMaterial({
				uniforms,
				vertexShader: fluidVertexShader,
				fragmentShader: fluidFragmentShader,
				depthTest: false,
				depthWrite: false
			});
			const mesh: Mesh = new THREE.Mesh(geometry, material);
			let animationFrame = 0;
			let lastFrameTime = 0;
			let time = 0;
			let timeSpeed = 0.006;
			let targetTimeSpeed = 0.006;
			let morphAmount = 0;
			let targetMorph = 0;
			let cursorEnergy = 0;

			renderer.setClearColor(0x000000, 0);
			fluidHost.appendChild(renderer.domElement);
			scene.add(mesh);

			const resizeFluid = () => {
				if (!fluidHost) return;
				const rect = fluidHost.getBoundingClientRect();
				const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.2);
				const width = Math.max(1, rect.width);
				const height = Math.max(1, rect.height);
				renderer.setPixelRatio(pixelRatio);
				renderer.setSize(width, height, false);
				uniforms.u_resolution.value.set(width * pixelRatio, height * pixelRatio);
			};

			triggerFluid = (strength = 0.32) => {
				cursorEnergy = Math.min(0.5, Math.max(cursorEnergy, strength));
			};

			const animate = (frameTime: number) => {
				animationFrame = window.requestAnimationFrame(animate);
				if (frameTime - lastFrameTime < 1000 / 30) return;
				lastFrameTime = frameTime;

				const elapsed = frameTime * 0.001;
				const ambientMorph = 0.16 + (0.5 + 0.5 * Math.sin(elapsed * 0.22)) * 0.18;
				targetMorph = Math.min(0.78, ambientMorph + cursorEnergy);
				targetTimeSpeed = 0.0055 + ambientMorph * 0.006 + cursorEnergy * 0.022;
				timeSpeed += (targetTimeSpeed - timeSpeed) * 0.045;
				time += timeSpeed;
				morphAmount += (targetMorph - morphAmount) * 0.05;
				cursorEnergy += (0 - cursorEnergy) * 0.025;

				uniforms.u_time.value = time;
				uniforms.u_morph.value = morphAmount;
				uniforms.u_pointer.value.set(pointer.x, pointer.y);
				renderer.render(scene, camera);
			};

			resizeFluid();
			window.addEventListener('resize', resizeFluid);
			animationFrame = window.requestAnimationFrame(animate);

			cleanupFluid = () => {
				window.removeEventListener('resize', resizeFluid);
				window.cancelAnimationFrame(animationFrame);
				geometry.dispose();
				material.dispose();
				renderer.dispose();
				renderer.domElement.remove();
			};
		})();

		return () => {
			disposed = true;
			window.removeEventListener('scroll', updateNavTheme);
			window.removeEventListener('resize', updateNavTheme);
			cleanupFluid?.();
			triggerFluid = null;
		};
	});

	function goToApp() {
		window.location.href = '/app';
	}

	function updateFieldPointer(event: PointerEvent) {
		const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
		pointer.x = (event.clientX - rect.left) / rect.width;
		pointer.y = 1 - (event.clientY - rect.top) / rect.height;
		triggerFluid?.(0.36);
	}

	function releaseFieldPointer() {
		triggerFluid?.(0.04);
	}

	const pathways = [
		'Architectural massing',
		'Stylized objects',
		'Low-poly scenes',
		'Product concepts'
	];

	const workflow = [
		{
			title: 'Describe the vibe',
			body: 'Start from rough language, references, and intent instead of a blank viewport.'
		},
		{
			title: 'Discover the form',
			body: 'Generate expressive 3D directions while the idea is still loose and alive.'
		},
		{
			title: 'Edit the parts',
			body: 'Use metadata-driven controls to reshape source parts without losing the model.'
		},
		{
			title: 'Export the model',
			body: 'Move from live exploration into portable OBJ when it is ready to leave Spellshape.'
		}
	];
</script>

<svelte:head>
	<title>Spellshape</title>
	<meta
		name="description"
		content="A cinematic Spellshape landing page direction inspired by Runway."
	/>
</svelte:head>

<div class="runway-page">
	<header class="site-header">
		<nav class:open={menuOpen} class:light={navLight} class="site-nav" aria-label="Primary">
			<a class="brand" href="/" aria-label="Spellshape home">
				<img src="/images/spellshape_text_logo.svg" alt="Spellshape" />
			</a>
			<div class="nav-links">
				<a
					href="https://github.com/StepanKukharskiy/live-obj"
					target="_blank"
					rel="noopener noreferrer"
					onclick={() => (menuOpen = false)}>GitHub</a
				>
				<a
					href="https://discord.gg/58zSgpaGc"
					target="_blank"
					rel="noopener noreferrer"
					onclick={() => (menuOpen = false)}>Discord</a
				>
				<a
					href="https://www.linkedin.com/company/spellshape/"
					target="_blank"
					rel="noopener noreferrer"
					onclick={() => (menuOpen = false)}>LinkedIn</a
				>
			</div>
			<button
				class="menu-button"
				type="button"
				aria-label="Toggle navigation"
				aria-expanded={menuOpen}
				onclick={() => (menuOpen = !menuOpen)}
			>
				<span></span>
				<span></span>
			</button>
		</nav>
	</header>

	<main>
		<section
			class="hero"
			aria-labelledby="hero-title"
			onpointermove={updateFieldPointer}
			onpointerleave={releaseFieldPointer}
		>
			<div class="hero-shade"></div>
			<div bind:this={fluidHost} class="fluid-field" aria-hidden="true"></div>

			<div class="hero-content">
				<p class="eyebrow">AI-native 3D modelling</p>
				<h1 id="hero-title">Transform your wildest ideas into fluid 3D forms</h1>
				<p class="hero-note">Runs with your own API key. No subscription required.</p>
				<div class="hero-actions">
					<button class="primary-button" onclick={goToApp}>Open Spellshape</button>
					<a class="secondary-button" href="/downloads/spellshape-grasshopper.gh" download
						>Download .gh</a
					>
				</div>
			</div>
		</section>

		<section class="video-showcase" aria-label="Spellshape video preview">
			<video
				class="showcase-video"
				src={gehryVideo}
				autoplay
				muted
				loop
				playsinline
				aria-label="Spellshape generating a Gehry-inspired pavilion"
			></video>
		</section>

		<section class="pathways" aria-label="Use cases">
			{#each pathways as pathway}
				<a href="/app">{pathway} ↗</a>
			{/each}
		</section>

		<section class="thesis">
			<p>
				Designed by architects for architects, fashion designers, game designers, and creators.
				It’s your ultimate playground for architectural massing, stylized objects, low-poly scenes,
				product concepts, and sculptural forms.
			</p>
		</section>

		<section class="studio-grid" aria-label="Spellshape workflow">
			<article class="large-panel">
				<p class="eyebrow">Live OBJ workflow</p>
				<h2>Vibe modelling for the messy stage before CAD.</h2>
				<p>
					Prompt, inspect, tune metadata, and keep moving while the form is still becoming
					itself.
				</p>
			</article>

			<div class="workflow-list">
				{#each workflow as item}
					<article class="workflow-card">
						<h3>{item.title}</h3>
						<p>{item.body}</p>
					</article>
				{/each}
			</div>
		</section>

		<section class="credits">
			<p>
				Vision -
				<a
					href="https://www.linkedin.com/in/alina-chereyskaya-architect/"
					target="_blank"
					rel="noopener noreferrer">Alina Chereyskaya</a
				>
				/ Tech -
				<a
					href="https://www.linkedin.com/in/stepan-kukharskiy/"
					target="_blank"
					rel="noopener noreferrer">Stepan Kukharskiy</a
				>
			</p>
		</section>
	</main>

	<footer class="site-footer">
		<p>&copy; 2026 Spellshape. Portable OBJ. Editable in Spellshape. AI-native by design.</p>
	</footer>
</div>

<style>
	:global(body) {
		margin: 0;
		background: #02022a;
		color: #f7f7fb;
	}

	:global(*) {
		box-sizing: border-box;
	}

	.runway-page {
		min-height: 100vh;
		background: #02022a;
		font-family:
			Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
	}

	.site-header {
		position: sticky;
		top: 0;
		left: 0;
		right: 0;
		z-index: 10;
		padding: 14px clamp(14px, 3vw, 28px);
		background: transparent;
	}

	.site-nav {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 22px;
		width: min(1280px, 100%);
		margin: 0 auto;
		padding: 12px 14px 12px 20px;
		border: 1px solid rgba(255, 255, 255, 0.14);
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.1);
		box-shadow:
			0 20px 60px rgba(0, 0, 235, 0.14),
			inset 0 1px 0 rgba(255, 255, 255, 0.12);
		backdrop-filter: blur(22px) saturate(1.28);
		-webkit-backdrop-filter: blur(22px) saturate(1.28);
		transition:
			background 0.2s ease,
			border-color 0.2s ease,
			box-shadow 0.2s ease;
	}

	.site-nav.light {
		border-color: rgba(0, 0, 235, 0.08);
		background: rgba(255, 255, 255, 0.72);
		box-shadow:
			0 18px 54px rgba(0, 0, 235, 0.1),
			inset 0 1px 0 rgba(255, 255, 255, 0.9);
	}

	.brand {
		display: flex;
		align-items: center;
	}

	.brand img {
		width: 148px;
		height: auto;
		filter: brightness(0) invert(1);
		transition: filter 0.2s ease;
	}

	.site-nav.light .brand img {
		filter: none;
	}

	.nav-links {
		display: flex;
		align-items: center;
		gap: 24px;
		margin-right: 8px;
	}

	.nav-links a {
		color: rgba(255, 255, 255, 0.72);
		font-size: 14px;
		font-weight: 700;
		text-decoration: none;
		transition: color 0.2s ease;
	}

	.nav-links a:hover {
		color: #ffffff;
	}

	.site-nav.light .nav-links a {
		color: rgba(8, 8, 22, 0.7);
	}

	.site-nav.light .nav-links a:hover {
		color: #0000eb;
	}

	.menu-button {
		display: none;
		width: 42px;
		height: 38px;
		align-items: center;
		justify-content: center;
		flex-direction: column;
		gap: 5px;
		border: 1px solid rgba(255, 255, 255, 0.24);
		border-radius: 999px;
		background: transparent;
		cursor: pointer;
	}

	.site-nav.light .menu-button {
		border-color: rgba(0, 0, 235, 0.16);
	}

	.menu-button span {
		width: 16px;
		height: 2px;
		border-radius: 999px;
		background: #ffffff;
	}

	.site-nav.light .menu-button span {
		background: #0000eb;
	}

	.hero {
		--g1x: 48%;
		--g1y: 24%;
		--g2x: 72%;
		--g2y: 58%;
		--g3x: 29%;
		--g3y: 66%;
		--g4x: 58%;
		--g4y: 78%;
		position: relative;
		min-height: calc(100vh - 86px);
		display: flex;
		align-items: center;
		justify-content: center;
		overflow: hidden;
		padding: clamp(110px, 14vw, 170px) clamp(18px, 4vw, 56px) clamp(80px, 10vw, 132px);
		margin-top: -86px;
	}

	.hero-shade {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
		z-index: 0;
	}

	.hero-shade {
		background: linear-gradient(180deg, #02022a 0%, #050566 52%, #02022a 100%);
	}

	.fluid-field {
		position: absolute;
		inset: 0;
		display: block;
		width: 100%;
		height: 100%;
		z-index: 1;
		opacity: 0.96;
		pointer-events: none;
	}

	.fluid-field :global(canvas) {
		display: block;
		width: 100%;
		height: 100%;
	}

	.hero-content {
		position: relative;
		z-index: 2;
		width: min(1040px, 100%);
		text-align: center;
	}

	.eyebrow {
		margin: 0 0 18px;
		color: rgba(255, 255, 255, 0.68);
		font-size: 13px;
		font-weight: 800;
		text-transform: uppercase;
	}

	h1,
	h2,
	h3,
	p {
		margin-top: 0;
	}

	h1 {
		margin-bottom: 22px;
		font-size: clamp(56px, 9vw, 124px);
		font-weight: 800;
		letter-spacing: 0;
		line-height: 0.92;
		text-wrap: balance;
	}

	.hero-note {
		margin: 0 auto 26px;
		max-width: 420px;
		color: rgba(255, 255, 255, 0.7);
		font-size: 15px;
		line-height: 1.5;
	}

	.hero-actions {
		display: flex;
		justify-content: center;
		flex-wrap: wrap;
		gap: 12px;
	}

	.primary-button,
	.secondary-button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-height: 52px;
		padding: 0 24px;
		border: 1px solid rgba(255, 255, 255, 0.24);
		border-radius: 999px;
		font: inherit;
		font-size: 15px;
		font-weight: 800;
		text-decoration: none;
		cursor: pointer;
		transition:
			background 0.2s ease,
			color 0.2s ease,
			transform 0.2s ease;
	}

	.primary-button {
		background: #ffffff;
		color: #0000eb;
	}

	.secondary-button {
		background: rgba(255, 255, 255, 0.08);
		color: #ffffff;
	}

	.primary-button:hover,
	.secondary-button:hover {
		transform: translateY(-2px);
	}

	.video-showcase {
		padding: clamp(22px, 4vw, 56px);
		background: #02022a;
	}

	.showcase-video {
		display: block;
		width: min(1280px, 100%);
		height: auto;
		max-height: min(78vh, 760px);
		aspect-ratio: 16 / 9;
		margin: 0 auto;
		border-radius: 12px;
		object-fit: cover;
		box-shadow: 0 30px 90px rgba(0, 0, 0, 0.28);
	}

	.pathways {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 1px;
		background: rgba(255, 255, 255, 0.1);
		border-top: 1px solid rgba(255, 255, 255, 0.1);
		border-bottom: 1px solid rgba(255, 255, 255, 0.1);
	}

	.pathways a {
		display: flex;
		align-items: center;
		min-height: 84px;
		padding: 22px clamp(18px, 3vw, 34px);
		background: #02022a;
		color: rgba(255, 255, 255, 0.78);
		font-size: 16px;
		font-weight: 760;
		text-decoration: none;
	}

	.pathways a:hover {
		color: #ffffff;
		background: #0000eb;
	}

	.thesis {
		padding: clamp(76px, 12vw, 160px) clamp(18px, 5vw, 72px);
		background: #ffffff;
		color: #080816;
	}

	.thesis p {
		max-width: 1120px;
		margin: 0 auto;
		font-size: clamp(34px, 5.2vw, 78px);
		font-weight: 760;
		line-height: 1.02;
		text-wrap: balance;
	}

	.studio-grid {
		display: grid;
		grid-template-columns: 0.9fr 1.1fr;
		gap: 18px;
		padding: clamp(18px, 4vw, 56px);
		background: #f4f4f6;
		color: #080816;
	}

	.large-panel,
	.workflow-card {
		border-radius: 8px;
		background: #ffffff;
	}

	.large-panel {
		min-height: 560px;
		display: flex;
		flex-direction: column;
		justify-content: flex-end;
		padding: clamp(26px, 4vw, 46px);
		background:
			linear-gradient(180deg, rgba(0, 0, 235, 0.12), rgba(255, 255, 255, 0) 45%),
			#ffffff;
	}

	.large-panel h2 {
		max-width: 620px;
		margin-bottom: 18px;
		font-size: clamp(38px, 5vw, 76px);
		font-weight: 800;
		letter-spacing: 0;
		line-height: 0.96;
		text-wrap: balance;
	}

	.large-panel p:last-child {
		max-width: 520px;
		margin-bottom: 0;
		color: rgba(8, 8, 22, 0.62);
		font-size: 18px;
		line-height: 1.5;
	}

	.workflow-list {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 18px;
	}

	.workflow-card {
		min-height: 270px;
		display: flex;
		flex-direction: column;
		justify-content: flex-end;
		padding: 26px;
	}

	.workflow-card h3 {
		margin-bottom: 12px;
		font-size: clamp(24px, 3vw, 36px);
		font-weight: 780;
		letter-spacing: 0;
		line-height: 1;
	}

	.workflow-card p {
		margin: 0;
		color: rgba(8, 8, 22, 0.62);
		font-size: 15px;
		line-height: 1.5;
	}

	.credits {
		padding: clamp(58px, 9vw, 112px) clamp(18px, 5vw, 72px);
		background: #ffffff;
		color: #080816;
		text-align: center;
	}

	.credits p {
		margin: 0;
		font-size: clamp(22px, 3vw, 40px);
		font-weight: 720;
		line-height: 1.2;
	}

	.credits a {
		color: #0000eb;
		text-decoration: none;
	}

	.credits a:hover {
		text-decoration: underline;
	}

	.site-footer {
		padding: 28px clamp(18px, 5vw, 72px);
		background: #02022a;
		color: rgba(255, 255, 255, 0.58);
		text-align: center;
	}

	.site-footer p {
		margin: 0;
		font-size: 14px;
		line-height: 1.4;
	}

	@media (max-width: 900px) {
		.pathways,
		.studio-grid,
		.workflow-list {
			grid-template-columns: 1fr;
		}

		.large-panel {
			min-height: 420px;
		}
	}

	@media (max-width: 680px) {
		.site-header {
			padding: 12px 14px;
		}

		.brand img {
			width: 140px;
		}

		.nav-links {
			display: none;
			position: absolute;
			top: calc(100% + 8px);
			right: 0;
			flex-direction: column;
			align-items: stretch;
			width: min(240px, calc(100vw - 36px));
			padding: 10px;
			border-radius: 18px;
			background: rgba(2, 2, 42, 0.78);
			backdrop-filter: blur(18px);
			-webkit-backdrop-filter: blur(18px);
		}

		.site-nav {
			position: relative;
		}

		.site-nav.open .nav-links {
			display: flex;
		}

		.nav-links a {
			padding: 10px 12px;
		}

		.menu-button {
			display: flex;
		}

		.hero {
			min-height: calc(100vh - 74px);
			padding-top: 118px;
			margin-top: -74px;
		}

		h1 {
			font-size: clamp(48px, 15vw, 78px);
		}

		.hero-actions {
			align-items: stretch;
			flex-direction: column;
		}

		.primary-button,
		.secondary-button {
			width: 100%;
		}

		.workflow-card {
			min-height: 220px;
		}

		.video-showcase {
			padding: 18px;
		}

		.showcase-video {
			border-radius: 10px;
		}
	}
</style>
