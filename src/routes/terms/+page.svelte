<svelte:head>
	<title>Terms of Use | Spellshape</title>
	<meta
		name="description"
		content="Spellshape terms of use for the open-source, bring-your-own-key 3D authoring app."
	/>
</svelte:head>

<main class="legal-page">
	<a class="wordmark" href="/" aria-label="Spellshape home">
		<img src="/images/spellshape_text_logo.svg" alt="Spellshape" />
	</a>

	<article class="legal-document">
		<p class="eyebrow">Effective May 20, 2026</p>
		<h1>Terms of Use</h1>
		<p>
			These Terms govern your use of the hosted Spellshape app. Spellshape is an open-source,
			bring-your-own-key tool for AI-native 3D authoring with Live OBJ files.
		</p>

		<h2>Open Source</h2>
		<p>
			The Spellshape source code is provided as open-source software under the MIT License. These
			Terms apply to the hosted app experience and do not limit rights granted by the open-source
			license.
		</p>

		<h2>Your API Key and Provider Account</h2>
		<p>
			You are responsible for the API keys, provider accounts, model settings, endpoints, usage
			charges, quotas, and provider terms connected to your use of Spellshape. Spellshape forwards
			your requests to the provider you select, using the API key you provide.
		</p>

		<h2>Your Content and Outputs</h2>
		<p>
			You are responsible for prompts, images, scene data, Live OBJ files, and other materials you
			submit. You are also responsible for reviewing generated outputs before using, publishing,
			manufacturing, printing, or relying on them. AI-generated 3D outputs may be inaccurate,
			incomplete, unsafe, infringing, or unsuitable for your intended use.
		</p>

		<h2>Acceptable Use</h2>
		<p>You agree not to use Spellshape to:</p>
		<ul>
			<li>break the law or violate another person's rights;</li>
			<li>submit content you do not have the right to use;</li>
			<li>attempt to extract, misuse, or interfere with other users' API keys or data;</li>
			<li>attack, overload, scrape, or disrupt the app or its infrastructure;</li>
			<li>generate content for harmful, deceptive, or abusive purposes.</li>
		</ul>

		<h2>No Professional Advice</h2>
		<p>
			Spellshape is a creative and technical authoring tool. It does not provide architectural,
			engineering, manufacturing, safety, legal, or professional advice. You should independently
			validate dimensions, structural properties, tolerances, materials, and safety before
			real-world use.
		</p>

		<h2>Service Changes</h2>
		<p>
			We may change, suspend, or discontinue the hosted app or any feature at any time. Because the
			project is open source, you may also run your own copy subject to the project license and any
			third-party terms that apply.
		</p>

		<h2>Disclaimer</h2>
		<p>
			The hosted app is provided "as is" and "as available." To the maximum extent allowed by law,
			Spellshape disclaims warranties of merchantability, fitness for a particular purpose,
			non-infringement, availability, accuracy, and error-free operation.
		</p>

		<h2>Limitation of Liability</h2>
		<p>
			To the maximum extent allowed by law, Spellshape and its maintainers will not be liable for
			indirect, incidental, special, consequential, exemplary, or punitive damages, or for lost
			profits, lost data, provider charges, or damage arising from your use of the app or generated
			outputs.
		</p>

		<h2>Changes</h2>
		<p>
			We may update these Terms as the app changes. The effective date above shows when this version
			took effect. Continued use of the hosted app means you accept the updated Terms.
		</p>

		<h2>Contact</h2>
		<p>
			For questions, contact the maintainers through the
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
