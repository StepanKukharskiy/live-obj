<script lang="ts">
	import gehryVideo from '$lib/assets/Gehry.mp4';

	let menuOpen = $state(false);

	function goToApp() {
		window.location.href = '/app';
	}
</script>

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

	<main class="landing-main">
		<section class="hero">
			<div class="hero-copy">
				<h1>Discover 3D forms from text</h1>
				<p class="hero-subtitle">
					Spellshape turns rough ideas and visual vibes into expressive 3D shapes you can explore,
					edit, and export.
				</p>
				<p class="hero-tagline">Vibe modelling for the messy stage before CAD.</p>
			</div>

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

			<div class="video-section">
				<div class="video-placeholder">
					<video
						class="hero-video"
						src={gehryVideo}
						autoplay
						muted
						loop
						playsinline
						aria-label="Spellshape generating a Gehry-inspired pavilion"
					></video>
				</div>
			</div>
		</section>

		<section class="use-cases">
			<h2>Built for early 3D exploration</h2>
			<p>
				Use Spellshape for architectural massing, stylized objects, low-poly scenes, product
				concepts, and sculptural forms.
			</p>
			<p class="use-cases-tagline">
				Describe the vibe. Discover the form. Edit the parts. Export the model.
			</p>
		</section>

		<section class="credits">
			<p class="credits-text">
				<span class="credit-item"
					>Vision - <a
						href="https://www.linkedin.com/in/alina-chereyskaya-architect/"
						target="_blank"
						rel="noopener noreferrer">Alina Chereyskaya</a
					></span
				>
				<span class="credit-separator">•</span>
				<span class="credit-item"
					>Tech - <a
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
	}

	.landing {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
		background: linear-gradient(135deg, #f5f7fa 0%, #e8ebf2 100%);
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
		position: relative;
	}

	.video-section {
		position: relative;
		width: 100%;
		margin: 0 auto;
		padding: 0;
	}

	.hero-video {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.landing-header {
		padding: 0 24px;
		display: flex;
		align-items: center;
		justify-content: center;
		position: sticky;
		top: 0;
		z-index: 10;
	}

	.landing-nav {
		display: flex;
		align-items: center;
		gap: 22px;
		justify-content: space-between;
		width: min(760px, 100%);
		padding: 12px 18px 12px 24px;
		border: 1px solid rgba(255, 255, 255, 0.7);
		border-top: none;
		border-radius: 0 0 28px 28px;
		background: rgba(255, 255, 255, 0.68);
		box-shadow: 0 18px 48px rgba(20, 28, 46, 0.12);
		backdrop-filter: blur(18px) saturate(1.35);
		-webkit-backdrop-filter: blur(18px) saturate(1.35);
		position: relative;
	}

	.nav-logo-link {
		display: flex;
		align-items: center;
	}

	.landing-logo {
		display: block;
		width: 148px;
		height: auto;
	}

	.nav-links {
		display: flex;
		align-items: center;
		gap: 18px;
	}

	.nav-link {
		color: #0000eb;
		font-size: 15px;
		font-weight: 600;
		text-decoration: none;
	}

	.nav-link:hover {
		text-decoration: underline;
	}

	.nav-menu-button {
		display: none;
		width: 38px;
		height: 32px;
		align-items: center;
		justify-content: center;
		flex-direction: column;
		gap: 5px;
		border: 1px solid rgba(0, 0, 235, 0.16);
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.48);
		cursor: pointer;
	}

	.nav-menu-button span {
		display: block;
		width: 14px;
		height: 2px;
		border-radius: 999px;
		background: #0000eb;
	}

	.nav-menu-button:hover {
		background: rgba(0, 0, 235, 0.06);
	}

	.landing-main {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 56px;
		padding: 48px 24px;
		max-width: 1200px;
		margin: 0 auto;
		position: relative;
		z-index: 1;
	}

	.hero {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 28px;
		text-align: center;
		max-width: 800px;
	}

	.hero h1 {
		font-size: 56px;
		font-weight: 700;
		color: #1a1a1a;
		margin: 0;
		line-height: 1.1;
	}

	.hero-copy {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 12px;
	}

	.hero-subtitle {
		font-size: 20px;
		color: #555;
		margin: 0;
		line-height: 1.5;
	}

	.hero-tagline {
		font-size: 18px;
		color: #1a1a1a;
		margin: 0;
		line-height: 1.4;
		font-weight: 600;
	}

	.hero-actions {
		display: flex;
		gap: 12px;
		justify-content: center;
		align-items: center;
		flex-wrap: wrap;
	}

	.hero-note {
		color: #666;
		font-size: 14px;
		line-height: 1.4;
		margin: -16px 0 0;
	}

	.video-placeholder {
		width: 100%;
		max-width: 800px;
		aspect-ratio: 16/9;
		background: #0f1117;
		border-radius: 12px;
		margin: 0 auto;
		box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
		overflow: hidden;
	}

	.cta-button {
		background: #0000eb;
		color: white;
		border: none;
		padding: 16px 48px;
		font-size: 18px;
		font-weight: 600;
		border-radius: 999px;
		cursor: pointer;
		transition: all 0.2s ease;
		box-shadow: 0 4px 12px rgba(0, 0, 235, 0.3);
	}

	.secondary-button {
		background: transparent;
		color: #0000eb;
		border: 1px solid rgba(0, 0, 235, 0.3);
		padding: 15px 32px;
		font-size: 18px;
		font-weight: 600;
		border-radius: 999px;
		cursor: pointer;
		text-decoration: none;
		transition: all 0.2s ease;
	}

	.cta-button:hover {
		background: #0000a8;
		transform: translateY(-2px);
		box-shadow: 0 6px 16px rgba(0, 0, 235, 0.4);
	}

	.secondary-button:hover {
		border-color: #0000eb;
		background: rgba(0, 0, 235, 0.06);
		transform: translateY(-2px);
	}

	.use-cases {
		display: flex;
		flex-direction: column;
		gap: 14px;
		text-align: left;
		width: 100%;
		max-width: 620px;
	}

	.use-cases h2 {
		color: #1a1a1a;
		font-size: 28px;
		line-height: 1.2;
		margin: 0;
	}

	.use-cases p {
		font-size: 18px;
		color: #555;
		margin: 0;
		line-height: 1.5;
	}

	.use-cases-tagline {
		color: #0000eb;
		font-weight: 600;
	}

	.credits {
		text-align: center;
		width: 100%;
		max-width: 900px;
	}

	.credits-text {
		font-size: 16px;
		color: #555;
		margin: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-wrap: wrap;
		gap: 16px;
	}

	.credit-item {
		font-weight: 500;
	}

	.credit-item a {
		color: #0000eb;
		text-decoration: none;
	}

	.credit-item a:hover {
		text-decoration: underline;
	}

	.credit-separator {
		color: #888;
	}

	.landing-footer {
		text-align: center;
		padding: 0;
		color: #888;
		font-size: 14px;
		position: relative;
		overflow: hidden;
		z-index: 1;
	}

	.landing-logo-bottom {
		width: 100%;
		height: auto;
		margin-bottom: -40px;
	}

	@media (max-width: 768px) {
		.hero h1 {
			font-size: 36px;
		}

		.hero-subtitle {
			font-size: 16px;
		}

		.hero-tagline {
			font-size: 16px;
		}

		.hero-actions {
			align-items: stretch;
			flex-direction: column;
		}

		.cta-button,
		.secondary-button {
			width: 100%;
			box-sizing: border-box;
		}

		.use-cases h2 {
			font-size: 24px;
		}

		.use-cases p {
			font-size: 16px;
		}

		.landing-header {
			padding: 0 16px;
		}

		.landing-nav {
			width: min(100%, 420px);
			padding: 10px 10px 10px 18px;
			border-radius: 0 0 24px 24px;
		}

		.landing-logo {
			width: 136px;
		}

		.nav-links {
			display: none;
			position: absolute;
			top: calc(100% + 8px);
			right: 0;
			flex-direction: column;
			align-items: stretch;
			min-width: 150px;
			gap: 0;
			padding: 8px;
			border: 1px solid rgba(255, 255, 255, 0.72);
			border-radius: 18px;
			background: rgba(255, 255, 255, 0.82);
			box-shadow: 0 18px 44px rgba(20, 28, 46, 0.14);
			backdrop-filter: blur(18px) saturate(1.35);
			-webkit-backdrop-filter: blur(18px) saturate(1.35);
		}

		.landing-nav.open .nav-links {
			display: flex;
		}

		.nav-link {
			padding: 10px 12px;
			border-radius: 12px;
		}

		.nav-link:hover {
			background: rgba(0, 0, 235, 0.06);
			text-decoration: none;
		}

		.nav-menu-button {
			display: flex;
		}

		.landing-main {
			gap: 40px;
			padding: 32px 16px;
		}
	}
</style>
