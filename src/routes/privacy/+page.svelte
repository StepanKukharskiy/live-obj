<svelte:head>
	<title>Privacy Policy | Spellshape</title>
	<meta
		name="description"
		content="Spellshape privacy policy for the open-source, bring-your-own-key 3D authoring app."
	/>
</svelte:head>

<main class="legal-page">
	<a class="wordmark" href="/" aria-label="Spellshape home">
		<img src="/images/spellshape_text_logo.svg" alt="Spellshape" />
	</a>

	<article class="legal-document">
		<p class="eyebrow">Effective May 20, 2026</p>
		<h1>Privacy Policy</h1>
		<p>
			Spellshape is an open-source, bring-your-own-key 3D authoring app. We do not require accounts,
			subscriptions, or signups to use the app.
		</p>

		<h2>What We Collect</h2>
		<p>
			When you use the hosted app, Spellshape may process the prompts, chat history, reference
			images, screenshots, Live OBJ scene data, model settings, provider endpoints, and API key you
			submit so the app can generate or edit your scene.
		</p>
		<p>
			If you enable "Remember provider settings on this device," those provider settings, including
			your API key, are stored in your browser's local storage on that device. If you do not enable
			it, the app keeps those settings only in the current browser session state.
		</p>
		<p>
			Our hosting provider may collect ordinary operational logs such as IP address, user agent,
			request time, route, status code, and error diagnostics. Spellshape does not use these logs to
			create user profiles.
		</p>

		<h2>How Requests Work</h2>
		<p>
			Spellshape sends generation requests from your browser to Spellshape server routes. Those
			routes forward the request content and your API key to the AI provider and endpoint you
			selected. Your API key is used as a credential for that provider request and is not
			intentionally stored by Spellshape on our servers.
		</p>

		<h2>How We Use Information</h2>
		<p>
			We use submitted information to provide app functionality, generate and edit Live OBJ scenes,
			render image previews when requested, debug errors, protect the service, and maintain the
			project.
		</p>

		<h2>Third Parties</h2>
		<p>
			Your selected AI provider receives the request content needed to perform the generation or
			image operation. That provider's own terms and privacy policy govern its handling of your API
			key, prompts, images, outputs, and usage. Our hosting provider may process operational logs to
			run the hosted app.
		</p>

		<h2>What We Do Not Do</h2>
		<ul>
			<li>We do not sell personal information.</li>
			<li>We do not run behavioral advertising.</li>
			<li>We do not require user accounts.</li>
			<li>We do not intentionally store your API key on Spellshape servers.</li>
		</ul>

		<h2>Your Controls</h2>
		<p>
			You can clear provider settings from the Provider tab, clear site data in your browser, remove
			your API key from the app, or use a self-hosted copy of the open-source project. You can also
			revoke or rotate API keys through your AI provider.
		</p>

		<h2>Children</h2>
		<p>
			Spellshape is not directed to children under 13, and we do not knowingly collect personal
			information from children under 13.
		</p>

		<h2>Changes</h2>
		<p>
			We may update this policy as the app changes. The effective date above shows when this version
			took effect.
		</p>

		<h2>Contact</h2>
		<p>
			For privacy questions, contact the maintainers through the
			<a href="https://github.com/StepanKukharskiy/live-obj">Spellshape GitHub repository</a>.
		</p>
	</article>
</main>

<style>
	:global(body) {
		margin: 0;
	}

	:global(*) {
		box-sizing: border-box;
	}

	.legal-page {
		min-height: 100vh;
		padding: 28px clamp(18px, 5vw, 72px) 64px;
		background: #f5f6f8;
		color: #111827;
		font-family:
			Inter,
			ui-sans-serif,
			system-ui,
			-apple-system,
			BlinkMacSystemFont,
			'Segoe UI',
			sans-serif;
	}

	.wordmark {
		display: inline-flex;
		margin-bottom: clamp(36px, 7vw, 80px);
	}

	.wordmark img {
		width: 168px;
		height: auto;
	}

	.legal-document {
		max-width: 820px;
		margin: 0 auto;
	}

	.eyebrow {
		margin: 0 0 12px;
		color: #5b5f6a;
		font-size: 13px;
		font-weight: 700;
		text-transform: uppercase;
	}

	h1 {
		margin: 0 0 22px;
		font-size: clamp(42px, 7vw, 72px);
		line-height: 0.95;
		letter-spacing: 0;
	}

	h2 {
		margin: 34px 0 10px;
		font-size: clamp(21px, 3vw, 28px);
		line-height: 1.15;
		letter-spacing: 0;
	}

	p,
	li {
		font-size: 17px;
		line-height: 1.65;
		color: #2f3440;
	}

	p {
		margin: 0 0 16px;
	}

	ul {
		margin: 0 0 16px;
		padding-left: 22px;
	}

	a {
		color: #0000eb;
		font-weight: 700;
		text-decoration: none;
	}

	a:hover {
		text-decoration: underline;
	}
</style>
