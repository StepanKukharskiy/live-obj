<script lang="ts">
	import gehryVideo from '$lib/assets/Gehry.mp4';
	import { onMount } from 'svelte';

	let menuOpen = $state(false);
	let navLight = $state(false);
	let fieldCanvas: HTMLCanvasElement | null = $state(null);
	let renderFieldNow: (() => void) | null = null;

	const pointer = {
		x: 0,
		y: 0,
		active: false
	};

	onMount(() => {
		const updateNavTheme = () => {
			navLight = window.scrollY > window.innerHeight * 0.82;
		};

		let animationFrame = 0;
		let lastFrameTime = 0;
		const targetFrameDuration = 1000 / 30;

		function resizeFieldCanvas() {
			const context = fieldCanvas?.getContext('2d');
			if (!fieldCanvas || !context) return;
			const rect = fieldCanvas.getBoundingClientRect();
			const density = 1;
			fieldCanvas.width = Math.max(1, Math.floor(rect.width * density));
			fieldCanvas.height = Math.max(1, Math.floor(rect.height * density));
			context.setTransform(density, 0, 0, density, 0, 0);
		}

		updateNavTheme();
		resizeFieldCanvas();
		window.addEventListener('scroll', updateNavTheme, { passive: true });
		window.addEventListener('resize', updateNavTheme);
		window.addEventListener('resize', resizeFieldCanvas);

		function drawVectorField(time: number, shouldContinue = true) {
			if (shouldContinue && time - lastFrameTime < targetFrameDuration) {
				animationFrame = window.requestAnimationFrame(drawVectorField);
				return;
			}

			lastFrameTime = time;
			const context = fieldCanvas?.getContext('2d');
			if (!fieldCanvas || !context) {
				if (shouldContinue) animationFrame = window.requestAnimationFrame(drawVectorField);
				return;
			}

			const rect = fieldCanvas.getBoundingClientRect();
			const density = 1;
			const nextWidth = Math.max(1, Math.floor(rect.width * density));
			const nextHeight = Math.max(1, Math.floor(rect.height * density));

			if (fieldCanvas.width !== nextWidth || fieldCanvas.height !== nextHeight) {
				fieldCanvas.width = nextWidth;
				fieldCanvas.height = nextHeight;
				context.setTransform(density, 0, 0, density, 0, 0);
			}

			if (!fieldCanvas || !context) return;
			const width = fieldCanvas.clientWidth;
			const height = fieldCanvas.clientHeight;
			if (width === 0 || height === 0) {
				if (shouldContinue) animationFrame = window.requestAnimationFrame(drawVectorField);
				return;
			}

			const spacing = Math.max(34, Math.min(60, width / 25));
			const lineLength = spacing * 0.76;
			const driftX = Math.sin(time * 0.00018) * spacing * 0.9;
			const driftY = Math.cos(time * 0.00016) * spacing * 0.72;
			const fieldPhase = time * 0.00042;
			const swirlPhase = time * 0.00034;

			context.clearRect(0, 0, width, height);
			context.lineCap = 'round';
			context.lineWidth = 1.45;
			context.shadowBlur = 0;
			context.globalCompositeOperation = 'lighter';

			for (let y = spacing * 0.55; y < height; y += spacing) {
				for (let x = spacing * 0.5; x < width; x += spacing) {
					const baseX =
						x +
						driftX +
						Math.sin(time * 0.00036 + y * 0.014 + x * 0.004) * spacing * 0.44;
					const baseY =
						y +
						driftY +
						Math.cos(time * 0.00032 + x * 0.011 - y * 0.004) * spacing * 0.38;
					const nx = baseX / width;
					const ny = baseY / height;
					let angle =
						Math.sin(nx * 5.2 + fieldPhase) * 0.64 +
						Math.cos(ny * 5.8 - fieldPhase * 0.9) * 0.54 +
						Math.sin((nx + ny) * 3.2 + swirlPhase) * 0.52 +
						nx * 1.1 -
						ny * 0.5;
					let intensity = 0.62;
					let drawX = baseX;
					let drawY = baseY;
					let pointerInfluence = 0;

					if (pointer.active) {
						const dx = x - pointer.x;
						const dy = y - pointer.y;
						const distance = Math.hypot(dx, dy) || 1;
						const radius = Math.min(width, height) * 0.58;
						pointerInfluence = Math.max(0, 1 - distance / radius);
						const smoothInfluence = pointerInfluence * pointerInfluence * (3 - 2 * pointerInfluence);
						const tangent = Math.atan2(dy, dx) + Math.PI / 2;
						const displacement = smoothInfluence * 120;

						drawX += (dx / distance) * displacement;
						drawY += (dy / distance) * displacement;
						angle = angle * (1 - smoothInfluence) + tangent * smoothInfluence;
						intensity += smoothInfluence * 1.05;
					}

					const pulse = 0.64 + Math.sin(time * 0.00042 + nx * 7 + ny * 5) * 0.2;
					const alpha = Math.min(0.95, intensity * pulse);
					const activeLineLength = lineLength * (1 + pointerInfluence * 0.8);
					const dx = Math.cos(angle) * activeLineLength;
					const dy = Math.sin(angle) * activeLineLength;
					context.strokeStyle = `rgba(204, 224, 255, ${alpha * 0.72})`;
					context.beginPath();
					context.moveTo(drawX - dx / 2, drawY - dy / 2);
					context.lineTo(drawX + dx / 2, drawY + dy / 2);
					context.stroke();
				}
			}

			context.globalCompositeOperation = 'source-over';

			if (shouldContinue) animationFrame = window.requestAnimationFrame(drawVectorField);
		}

		renderFieldNow = () => drawVectorField(window.performance.now(), false);

		animationFrame = window.requestAnimationFrame(drawVectorField);

		return () => {
			window.removeEventListener('scroll', updateNavTheme);
			window.removeEventListener('resize', updateNavTheme);
			window.removeEventListener('resize', resizeFieldCanvas);
			window.cancelAnimationFrame(animationFrame);
			renderFieldNow = null;
		};
	});

	function goToApp() {
		window.location.href = '/app';
	}

	function updateFieldPointer(event: PointerEvent) {
		const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
		pointer.x = event.clientX - rect.left;
		pointer.y = event.clientY - rect.top;
		pointer.active = true;
		renderFieldNow?.();
	}

	function releaseFieldPointer() {
		pointer.active = false;
		renderFieldNow?.();
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
			<canvas bind:this={fieldCanvas} class="vector-field" aria-hidden="true"></canvas>

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

	.vector-field {
		position: absolute;
		inset: 0;
		display: block;
		width: 100%;
		height: 100%;
		z-index: 1;
		opacity: 0.92;
		pointer-events: none;
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
