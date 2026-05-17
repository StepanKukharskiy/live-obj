<script lang="ts">
	import gehryVideo from '$lib/assets/Gehry.mp4';

	function goToApp() {
		window.location.href = '/app';
	}
</script>

<div class="landing">
	<header class="landing-header">
		<img class="landing-logo" src="/images/spellshape_text_logo.svg" alt="Spellshape" />
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
				<a class="secondary-button" href="/downloads/spellshape-grasshopper.gh" download
					>Download .gh</a
				>
			</div>

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

			<div class="link-buttons">
				<a
					class="github-link"
					href="https://github.com/StepanKukharskiy/live-obj"
					target="_blank"
					rel="noopener noreferrer"
				>
					GitHub
				</a>
				<a
					class="discord-link"
					href="https://discord.gg/58zSgpaGc"
					target="_blank"
					rel="noopener noreferrer"
				>
					Discord
				</a>
			</div>
		</section>

		<section class="platforms">
			<p class="platforms-text">
				<span class="platform-item">Web <span class="platform-status beta">(Beta)</span></span>
				<span class="platform-separator">•</span>
				<span class="platform-item">
					Grasshopper <span class="platform-status beta">(Beta)</span>
				</span>
				<span class="platform-separator">•</span>
				<span class="platform-item"
					>Blender <span class="platform-status coming-soon">(Coming Soon)</span></span
				>
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
		padding: 32px 24px 0;
		display: flex;
		align-items: center;
		justify-content: center;
		position: relative;
		z-index: 1;
	}

	.landing-logo {
		width: 220px;
		max-width: 60vw;
		height: auto;
	}

	.link-buttons {
		display: flex;
		gap: 24px;
		justify-content: center;
	}

	.github-link,
	.discord-link {
		color: #0000eb;
		text-decoration: none;
		font-weight: 600;
		font-size: 16px;
		display: inline-block;
	}

	.github-link:hover,
	.discord-link:hover {
		text-decoration: underline;
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

	.video-placeholder {
		width: 100%;
		max-width: 800px;
		aspect-ratio: 16/9;
		background: #0f1117;
		border-radius: 16px;
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

	.platforms {
		text-align: center;
		width: 100%;
		max-width: 900px;
	}

	.platforms-text {
		font-size: 18px;
		color: #555;
		margin: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-wrap: wrap;
		gap: 16px;
	}

	.platform-item {
		font-weight: 500;
	}

	.platform-separator {
		color: #888;
	}

	.platform-status {
		font-size: 14px;
		font-weight: 500;
		color: #22c55e;
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

	.platform-status.beta {
		color: #f59e0b;
	}

	.platform-status.coming-soon {
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

		.platforms-text {
			font-size: 16px;
			flex-direction: column;
			gap: 8px;
		}

		.platform-separator {
			display: none;
		}

		.landing-header {
			padding: 24px 16px 0;
		}

		.landing-logo {
			width: 180px;
		}

		.landing-main {
			gap: 40px;
			padding: 32px 16px;
		}
	}
</style>
