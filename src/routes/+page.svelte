<script lang="ts">
	function goToApp() {
		window.location.href = '/app';
	}

	// Extract examples from tools section for background
	const toolsExamples = [
		'o wall\n#@source: procedural\n#@type: extrude\n#@params: kernel=cadquery, profile=[[0,0,0],[4,0,0],[4,0,3],[0,0,3]], height=0.2',
		'o lofted_shape\n#@source: procedural\n#@type: loft\n#@params: kernel=cadquery, sections=[[[0,0,0],[1,0,0],[1,1,0],[0,1,0]], [[0,0,2],[1.5,0,2],[1.5,1.5,2],[0,1.5,2]]]',
		'o swept_pipe\n#@source: procedural\n#@type: sweep\n#@params: kernel=cadquery, profile=[[0,0,0],[0.1,0,0],[0.1,0.1,0],[0,0.1,0]], along=[[0,0,0],[0,0,1],[0,1,2],[1,2,2]]',
		'o vase\n#@source: procedural\n#@type: revolve\n#@params: kernel=cadquery, profile=[[0,0,0],[0.1,0,0.2],[0.05,0,0.4],[0,0,0.8]], axis=z, angle=360',
		'o cube\n#@source: procedural\n#@type: box\n#@params: center=[0,0,0], size=[1,1,1]',
		'o ball\n#@source: procedural\n#@type: sphere\n#@params: center=[0,0,0], radius=0.5',
		'o column\n#@source: procedural\n#@type: cylinder\n#@params: center=[0,0,0], radius=0.5, height=1.0, axis=z',
		'o roof_cone\n#@source: procedural\n#@type: cone\n#@params: center=[0,0,1], radius=0.5, height=0.8, axis=z',
		'o capsule\n#@source: sdf\n#@sdf:\n#@ - capsule id=capsule a=[0,0,0] b=[0,0,1] radius=0.2',
		'o ring\n#@source: sdf\n#@sdf:\n#@ - torus id=ring center=[0,0,0] major=1.0 minor=0.2',
		'o line\n#@source: procedural\n#@type: polyline\n#@params: points=[[0,0,0],[1,0,0],[1,1,0]]',
		'#@sdf:\n#@ - box id=a center=[0,0,0] size=[1,1,1]\n#@ - box id=b center=[0.5,0,0] size=[1,1,1]\n#@ - union a b',
		'#@sdf:\n#@ - box id=base center=[0,0,0] size=[2,2,2]\n#@ - box id=cut center=[0.6,0.6,0] size=[1,1,1]\n#@ - subtract base cut',
		'#@sdf:\n#@ - box id=a center=[0,0,0] size=[1,1,1]\n#@ - box id=b center=[0.3,0.3,0] size=[1,1,1]\n#@ - intersect a b',
		'#@sdf:\n#@ - box id=a center=[0,0,0] size=[1,1,1]\n#@ - box id=b center=[0.5,0,0] size=[1,1,1]\n#@ - smooth_union radius=0.2 a b',
		'#@sdf:\n#@ - sphere id=s center=[0,0,0] radius=0.3\n#@ - repeat cell=[1,1,1]',
		'#@ops:\n#@ - move offset=[1,0,0]',
		'#@ops:\n#@ - scale factor=2.0',
		'#@ops:\n#@ - rotate angle=45 axis=z',
		'#@ops:\n#@ - mirror axis=x',
		'#@ops:\n#@ - array count=5 offset=[0.5,0,0]',
		'#@ops:\n#@ - array_linear count=3 offset=[0,0.3,0]',
		'#@ops:\n#@ - radial_array count=8 axis=z radius=1.0',
		'#@ops:\n#@ - taper axis=z amount=0.5',
		'#@ops:\n#@ - twist axis=z angle_deg=45',
		'#@ops:\n#@ - bend axis=x angle_deg=30',
		'#@ops:\n#@ - displace field=wave axis=z amplitude=0.15',
		'#@sdf:\n#@ - box id=base center=[0,0,0] size=[2,2,2]\n#@ - noise_displace strength=0.15 frequency=4 seed=3',
		'#@ops:\n#@ - subdivide level=2',
		'#@ops:\n#@ - smooth iterations=3 strength=0.5',
		'#@ops:\n#@ - simplify ratio=0.5',
		'#@ops:\n#@ - bevel amount=0.05 segments=2',
		'#@ops:\n#@ - chamfer distance=0.1',
		'#@ops:\n#@ - shell thickness=0.02',
		'#@ops:\n#@ - thicken thickness=0.03',
		'#@ops:\n#@ - offset amount=0.05',
		'#@ops:\n#@ - trace_paths sample_every=2',
		'#@ops:\n#@ - trace_paths sample_every=1\n#@ - sdf_tubes radius=0.03',
		'o grid\n#@source: procedural\n#@type: surface_grid\n#@params: width=10, depth=10, resolution=20',
		'o terrain\n#@source: procedural\n#@type: heightfield\n#@params: width=20, depth=20, resolution=30',
		'o custom\n#@source: procedural\n#@type: mesh\n#@params: generator=spiral_treads, count=12, total_height=3',
		'o path\n#@source: procedural\n#@type: curve\n#@params: points=[[0,0,0],[1,0,0.5],[2,0,1]]',
		'#@ops:\n#@ - voxelize resolution=0.1',
		'#@ops:\n#@ - mesh_from_volume resolution=0.15',
		'o stairs\n#@source: procedural\n#@type: mesh\n#@params: generator=spiral_treads, count=12, total_height=3',
		'#@sdf:\n#@ - sphere id=s center=[0,0,0] radius=0.5\n#@ - mesh_from_sdf resolution=0.1',
		'o coral\n#@source: simulation\n#@sim: cellular_automata\n#@params: grid=[32,32,32], cell=0.08, steps=45, seed=8, mode=coral',
		'o growth\n#@source: simulation\n#@sim: differential_growth\n#@params: radius=1.0, points=40, steps=180, split_distance=0.18, repel_radius=0.25, thickness=0.035, seed=2',
		'o boids_sim\n#@source: simulation\n#@sim: boids\n#@params: agents=40, steps=160, step_size=0.05, bounds=[8,5,5], seed=4, trace_radius=0.035',
		'o flow_field_sim\n#@source: simulation\n#@sim: flow_field\n#@params: agents=50, steps=200, step_size=0.1, bounds=[10,10,10], mode=curl-noise, frequency=1.0, octaves=3, strength=1.0, scale=0.1, time_scale=0.01, damping=0.0, seed=1, trace_radius=0.025'
	];

	// Create single continuous string (remove newlines)
	// Repeat examples to cover wide screens
	const repeatedExamples = [...toolsExamples, ...toolsExamples, ...toolsExamples];
	const backgroundText = repeatedExamples.join(' • ').replace(/\n/g, ' ');
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

			<div class="video-section">
				<div class="video-background-text">{backgroundText}</div>
				<div class="video-placeholder">
					<div class="video-placeholder-content">
						<div class="play-icon">▶</div>
						<p>Watch it in action</p>
					</div>
				</div>
			</div>

			<button class="cta-button" onclick={goToApp}>Try It Free</button>
		</section>

		<section class="platforms">
			<p class="platforms-text">
				<span class="platform-item">Web <span class="platform-status beta">(Beta)</span></span>
				<span class="platform-separator">•</span>
				<span class="platform-item">Grasshopper <span class="platform-status beta">(Beta)</span></span>
				<span class="platform-separator">•</span>
				<span class="platform-item">Blender <span class="platform-status coming-soon">(Coming Soon)</span></span>
			</p>
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
		position: relative;
	}

	.video-section {
		position: relative;
		width: 100%;
		margin: 0 auto 48px auto;
		padding: 40px 0;
	}

	.video-background-text {
		position: absolute;
		top: 0;
		left: 50%;
		transform: translateX(-50%);
		width: 100vw;
		height: 100%;
		font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
		font-size: 14px;
		line-height: 1.4;
		color: rgba(0, 0, 235, 0.15);
		padding: 0;
		overflow: hidden;
		word-wrap: break-word;
		word-break: break-all;
		pointer-events: none;
		mask-image: linear-gradient(to bottom, transparent 0%, black 15%, black 85%, transparent 100%);
		-webkit-mask-image: linear-gradient(to bottom, transparent 0%, black 15%, black 85%, transparent 100%);
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
		margin: 0 auto;
		box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
		position: relative;
		z-index: 1;
	}

	.landing-header {
		padding: 0;
		display: flex;
		align-items: center;
		position: relative;
		margin-top: -40px;
		z-index: 1;
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
		position: relative;
		z-index: 1;
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

	.platforms {
		text-align: center;
		margin-bottom: 80px;
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

		.platforms-text {
			font-size: 16px;
			flex-direction: column;
			gap: 8px;
		}

		.platform-separator {
			display: none;
		}

		.landing-header {
			padding: 16px 24px;
		}

		.landing-main {
			padding: 32px 16px;
		}
	}
</style>
