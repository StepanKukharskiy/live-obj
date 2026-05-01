<script lang="ts">
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
			<h1>Create 3D Models by Just Describing Them</h1>
			<p class="hero-subtitle">
				No complex software. No technical skills needed. Just type what you want to build.
			</p>

			<a class="github-link" href="https://github.com/StepanKukharskiy/live-obj" target="_blank" rel="noopener noreferrer">
				GitHub
			</a>

			<div class="video-placeholder">
				<div class="video-placeholder-content">
					<div class="play-icon">▶</div>
					<p>Watch it in action</p>
				</div>
			</div>

			<button class="cta-button" onclick={goToApp}>Try It Free</button>
		</section>

		<section class="problem-solution">
			<div class="problem">
				<h2>The Problem</h2>
				<p>
					Traditional 3D modeling requires expensive software, months of training, and deep technical knowledge.
					It's slow, frustrating, and out of reach for most people.
				</p>
			</div>

			<div class="solution">
				<h2>The Solution</h2>
				<p>
					Spellshape lets you create 3D models simply by describing what you want in plain English.
					Our AI understands your description and generates the model instantly. Edit, refine, and export—all in one place.
				</p>
			</div>
		</section>
	</main>

	<footer class="landing-footer">
	<p>&copy; 2026 Spellshape. AI-native 3D.</p>
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
	}

	.landing-header {
		padding: 0;
		display: flex;
		align-items: center;
		position: relative;
		margin-top: -40px;
	}

	.landing-logo {
		width: 100%;
		height: auto;
	}

	.github-link {
		color: #0000eb;
		text-decoration: none;
		font-weight: 600;
		font-size: 16px;
		margin-bottom: 24px;
		display: inline-block;
	}

	.github-link:hover {
		text-decoration: underline;
	}

	.landing-main {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 48px 24px;
		max-width: 1200px;
		margin: 0 auto;
	}

	.hero {
		text-align: center;
		max-width: 800px;
		margin-bottom: 80px;
	}

	.hero h1 {
		font-size: 56px;
		font-weight: 700;
		color: #1a1a1a;
		margin: 0 0 24px 0;
		line-height: 1.1;
	}

	.hero-subtitle {
		font-size: 20px;
		color: #555;
		margin: 0 0 48px 0;
		line-height: 1.5;
	}

	.video-placeholder {
		width: 100%;
		max-width: 800px;
		aspect-ratio: 16/9;
		background: linear-gradient(135deg, #0000eb 0%, #0000a8 100%);
		border-radius: 16px;
		display: flex;
		align-items: center;
		justify-content: center;
		margin: 0 auto 48px auto;
		box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
	}

	.video-placeholder-content {
		text-align: center;
		color: white;
	}

	.play-icon {
		font-size: 64px;
		margin-bottom: 16px;
	}

	.video-placeholder-content p {
		font-size: 18px;
		font-weight: 500;
		margin: 0;
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

	.cta-button:hover {
		background: #0000a8;
		transform: translateY(-2px);
		box-shadow: 0 6px 16px rgba(0, 0, 235, 0.4);
	}

	.problem-solution {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 48px;
		width: 100%;
		max-width: 900px;
	}

	.problem,
	.solution {
		padding: 32px;
		background: white;
		border-radius: 16px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
	}

	.problem h2,
	.solution h2 {
		font-size: 24px;
		font-weight: 600;
		color: #1a1a1a;
		margin: 0 0 16px 0;
	}

	.problem p,
	.solution p {
		font-size: 16px;
		color: #555;
		line-height: 1.6;
		margin: 0;
	}

	.landing-footer {
		text-align: center;
		padding: 0;
		color: #888;
		font-size: 14px;
		position: relative;
		overflow: hidden;
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

		.problem-solution {
			grid-template-columns: 1fr;
			gap: 24px;
		}

		.landing-header {
			padding: 16px 24px;
		}

		.landing-main {
			padding: 32px 16px;
		}
	}
</style>
