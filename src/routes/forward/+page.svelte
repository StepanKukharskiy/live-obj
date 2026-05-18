<script lang="ts">
	import gehryVideo from '$lib/assets/Gehry.mp4';

	let menuOpen = $state(false);

	function goToApp() {
		window.location.href = '/app';
	}
</script>

<svelte:head>
	<title>Spellshape</title>
	<meta
		name="description"
		content="Spellshape turns rough ideas and visual vibes into expressive 3D shapes you can explore, edit, and export."
	/>
</svelte:head>

<div class="landing">
	<header class="landing-header">
		<nav class:open={menuOpen} class="landing-nav" aria-label="Primary">
			<a class="nav-logo-link" href="/" aria-label="Spellshape home">
				<img class="landing-logo" src="/images/spellshape_text_logo.svg" alt="Spellshape" />
			</a>
			<div class="nav-links">
				<a
					class="nav-link"
					href="https://github.com/StepanKukharskiy/live-obj"
					target="_blank"
					rel="noopener noreferrer"
					onclick={() => (menuOpen = false)}
				>
					GitHub
				</a>
				<a
					class="nav-link"
					href="https://discord.gg/58zSgpaGc"
					target="_blank"
					rel="noopener noreferrer"
					onclick={() => (menuOpen = false)}
				>
					Discord
				</a>
			</div>
			<button
				class="nav-menu-button"
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
		<section class="hero" aria-labelledby="hero-title">
			<div class="hero-copy">
				<p class="kicker">AI-native 3D authoring</p>
				<h1 id="hero-title">Transform your wildest ideas into fluid 3D forms</h1>
				<div class="hero-actions">
					<button class="cta-button" onclick={goToApp}>Open Spellshape</button>
					<a
						class="secondary-button"
						href="/downloads/spellshape-grasshopper.gh"
						download
						data-umami-event="Download Grasshopper GH">Download .gh</a
					>
				</div>
				<p class="hero-note">Runs with your own API key. No subscription required.</p>
			</div>

			<div class="hero-media">
				<video
					class="hero-video"
					src={gehryVideo}
					autoplay
					muted
					loop
					playsinline
					aria-label="Spellshape generating a Gehry-inspired pavilion"
				></video>
				<div class="media-label">
					<span>Describe the vibe.</span>
					<span>Discover the form.</span>
				</div>
			</div>
		</section>

		<section class="statement">
			<p>
				Designed by architects for architects, fashion designers, game designers, and creators. It’s
				your ultimate playground for architectural massing, stylized objects, low-poly scenes,
				product concepts, and sculptural forms. Vibe modelling for the messy stage before CAD.
			</p>
		</section>

		<section class="workflow" aria-label="Spellshape workflow">
			<div class="workflow-item">Describe the vibe.</div>
			<div class="workflow-item">Discover the form.</div>
			<div class="workflow-item">Edit the parts.</div>
			<div class="workflow-item">Export the model.</div>
		</section>

		<section class="credits">
			<p class="credits-text">
				<span class="credit-item"
					>Vision -
					<a
						href="https://www.linkedin.com/in/alina-chereyskaya-architect/"
						target="_blank"
						rel="noopener noreferrer">Alina Chereyskaya</a
					></span
				>
				<span class="credit-item"
					>Tech -
					<a
						href="https://www.linkedin.com/in/stepan-kukharskiy/"
						target="_blank"
						rel="noopener noreferrer">Stepan Kukharskiy</a
					></span
				>
			</p>
		</section>
	</main>

	<footer class="landing-footer">
		<p>&copy; 2026 Spellshape. Portable OBJ. Editable in Spellshape. AI-native by design.</p>
		<img class="landing-logo-bottom" src="/images/spellshape_text_logo.svg" alt="Spellshape" />
	</footer>
</div>

<style>
	:global(body) {
		margin: 0;
		padding: 0;
		background: #ffffff;
		color: #080816;
	}

	:global(*) {
		box-sizing: border-box;
	}

	.landing {
		min-height: 100vh;
		background: #ffffff;
		font-family:
			Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
	}

	.landing-header {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		z-index: 10;
		padding: 26px clamp(18px, 5vw, 72px);
	}

	.landing-nav {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 20px;
		width: min(1280px, 100%);
		margin: 0 auto;
	}

	.nav-logo-link {
		display: flex;
		align-items: center;
		min-width: 0;
	}

	.landing-logo {
		display: block;
		width: 148px;
		height: auto;
		filter: brightness(0) invert(1);
	}

	.nav-links {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.nav-link {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-height: 36px;
		padding: 0 16px;
		border-radius: 999px;
		color: rgba(255, 255, 255, 0.78);
		font-size: 13px;
		font-weight: 700;
		text-decoration: none;
		transition:
			background 0.2s ease,
			color 0.2s ease,
			color 0.2s ease;
	}

	.nav-link:hover {
		background: rgba(255, 255, 255, 0.12);
		color: #ffffff;
	}

	.nav-menu-button {
		display: none;
		width: 42px;
		height: 38px;
		align-items: center;
		justify-content: center;
		flex-direction: column;
		gap: 5px;
		border: 1px solid rgba(255, 255, 255, 0.28);
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.1);
		cursor: pointer;
	}

	.nav-menu-button span {
		width: 16px;
		height: 2px;
		border-radius: 999px;
		background: #ffffff;
	}

	main {
		width: 100%;
	}

	.hero {
		display: flex;
		align-items: center;
		flex-direction: column;
		min-height: 100vh;
		padding: clamp(120px, 16vw, 190px) clamp(18px, 5vw, 72px) clamp(58px, 7vw, 96px);
		background:
			linear-gradient(180deg, rgba(4, 4, 24, 0.78) 0%, rgba(4, 9, 42, 0) 28%),
			linear-gradient(180deg, #0000eb 0%, #7d9cff 50%, #ffffff 100%);
	}

	.hero-copy {
		display: flex;
		align-items: center;
		flex-direction: column;
		justify-content: center;
		width: min(1040px, 100%);
		padding: 0;
		text-align: center;
	}

	.kicker {
		width: fit-content;
		margin: 0 0 24px;
		padding: 0;
		border: 0;
		background: transparent;
		color: rgba(255, 255, 255, 0.74);
		font-size: 13px;
		font-weight: 800;
		letter-spacing: 0;
		text-transform: uppercase;
	}

	h1,
	p {
		margin-top: 0;
	}

	h1 {
		max-width: 980px;
		margin-bottom: 30px;
		color: #ffffff;
		font-size: clamp(48px, 8vw, 112px);
		font-weight: 780;
		letter-spacing: 0;
		line-height: 0.94;
		text-wrap: balance;
	}

	.hero-actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: 12px;
		margin-bottom: 18px;
	}

	.cta-button,
	.secondary-button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-height: 52px;
		padding: 0 24px;
		border: 1px solid rgba(255, 255, 255, 0.28);
		border-radius: 999px;
		font: inherit;
		font-size: 15px;
		font-weight: 760;
		text-decoration: none;
		cursor: pointer;
		transition:
			transform 0.2s ease,
			box-shadow 0.2s ease,
			background 0.2s ease,
			color 0.2s ease;
	}

	.cta-button {
		background: #ffffff;
		color: #0000eb;
		box-shadow: 0 18px 48px rgba(4, 10, 48, 0.18);
	}

	.secondary-button {
		background: rgba(255, 255, 255, 0.12);
		color: #ffffff;
	}

	.cta-button:hover,
	.secondary-button:hover {
		transform: translateY(-2px);
	}

	.hero-note {
		max-width: 360px;
		margin: 0;
		color: rgba(255, 255, 255, 0.72);
		font-size: 14px;
		line-height: 1.45;
	}

	.hero-media {
		position: relative;
		width: min(1120px, 100%);
		margin-top: clamp(52px, 8vw, 96px);
		padding: 10px;
		border-radius: 32px;
		background: #ffffff;
		box-shadow: 0 38px 90px rgba(8, 16, 54, 0.22);
		overflow: hidden;
	}

	.hero-video {
		display: block;
		width: 100%;
		height: 100%;
		min-height: min(54vh, 620px);
		border-radius: 24px;
		object-fit: cover;
		filter: saturate(0.96) contrast(1.02);
	}

	.media-label {
		position: absolute;
		left: 50%;
		bottom: clamp(22px, 4vw, 42px);
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: 10px;
		width: auto;
		padding: 8px;
		border: 1px solid rgba(255, 255, 255, 0.46);
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.74);
		box-shadow: 0 16px 34px rgba(5, 8, 28, 0.14);
		transform: translateX(-50%);
		backdrop-filter: blur(16px) saturate(1.1);
		-webkit-backdrop-filter: blur(16px) saturate(1.1);
	}

	.media-label span {
		padding: 9px 13px;
		border-radius: 999px;
		color: #0000eb;
		font-size: 13px;
		font-weight: 760;
		line-height: 1;
		white-space: nowrap;
	}

	.statement {
		padding: clamp(70px, 10vw, 138px) clamp(18px, 5vw, 72px);
		background: #ffffff;
	}

	.statement p {
		max-width: 980px;
		margin: 0 auto;
		color: #1d1d1f;
		font-size: clamp(28px, 4.4vw, 64px);
		font-weight: 700;
		letter-spacing: 0;
		line-height: 1.06;
		text-align: center;
		text-wrap: balance;
	}

	.workflow {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 14px;
		padding: 0 clamp(18px, 5vw, 72px) clamp(72px, 10vw, 132px);
		background: #ffffff;
	}

	.workflow-item {
		min-height: 190px;
		display: flex;
		align-items: flex-end;
		padding: 24px;
		border-radius: 24px;
		background: #f5f5f7;
		color: #080816;
		font-size: clamp(21px, 2.6vw, 34px);
		font-weight: 720;
		line-height: 1.05;
	}

	.workflow-item:nth-child(3) {
		background: #eef2ff;
	}

	.workflow-item:nth-child(4) {
		background: #0000eb;
		color: #ffffff;
	}

	.credits {
		padding: clamp(48px, 7vw, 84px) clamp(18px, 5vw, 72px);
		background: #f5f5f7;
	}

	.credits-text {
		display: flex;
		align-items: center;
		justify-content: center;
		max-width: 980px;
		margin: 0 auto;
		flex-wrap: wrap;
		gap: 12px;
		color: rgba(8, 8, 22, 0.72);
		font-size: clamp(20px, 3vw, 38px);
		font-weight: 680;
		line-height: 1.12;
	}

	.credit-item {
		display: inline-flex;
		align-items: baseline;
		gap: 8px;
	}

	.credit-item + .credit-item::before {
		content: '/';
		color: #0000eb;
	}

	.credit-item a {
		color: #0000eb;
		text-decoration: none;
	}

	.credit-item a:hover {
		text-decoration: underline;
	}

	.landing-footer {
		position: relative;
		overflow: hidden;
		padding: 36px clamp(18px, 5vw, 72px) 0;
		background: #ffffff;
		color: rgba(8, 8, 22, 0.7);
	}

	.landing-footer p {
		max-width: 760px;
		margin: 0 auto 32px;
		font-size: 16px;
		font-weight: 680;
		line-height: 1.4;
		text-align: center;
	}

	.landing-logo-bottom {
		display: block;
		width: 100%;
		height: auto;
		margin-bottom: -4vw;
		opacity: 0.1;
	}

	@media (max-width: 980px) {
		.hero-video {
			min-height: 54vw;
		}

		.workflow {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}

	@media (max-width: 680px) {
		.landing-nav {
			align-items: center;
		}

		.landing-logo {
			width: 140px;
		}

		.nav-links {
			display: none;
			position: absolute;
			top: calc(100% + 8px);
			right: 0;
			flex-direction: column;
			align-items: stretch;
			width: min(220px, calc(100vw - 32px));
			padding: 8px;
			border: 1px solid rgba(255, 255, 255, 0.74);
			border-radius: 22px;
			background: rgba(8, 8, 22, 0.42);
			box-shadow: 0 22px 54px rgba(5, 8, 28, 0.2);
			backdrop-filter: blur(20px) saturate(1.2);
			-webkit-backdrop-filter: blur(20px) saturate(1.2);
		}

		.landing-nav {
			position: relative;
		}

		.landing-nav.open .nav-links {
			display: flex;
		}

		.nav-link {
			width: 100%;
		}

		.nav-menu-button {
			display: flex;
		}

		h1 {
			font-size: clamp(44px, 15vw, 76px);
		}

		.hero-actions {
			align-items: stretch;
			flex-direction: column;
		}

		.cta-button,
		.secondary-button {
			width: 100%;
		}

		.hero-video {
			min-height: 360px;
		}

		.media-label {
			bottom: 18px;
			width: max-content;
			max-width: calc(100% - 36px);
		}

		.statement p {
			font-size: clamp(32px, 11vw, 58px);
		}

		.workflow {
			grid-template-columns: 1fr;
		}

		.workflow-item {
			min-height: 150px;
		}

		.credits-text {
			align-items: flex-start;
			flex-direction: column;
		}

		.credit-item + .credit-item::before {
			content: none;
		}
	}
</style>
