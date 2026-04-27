<script>
	import { onMount } from 'svelte';
	import { showSidePanel, currentChain, addLog, chatHistory, addChatMessage, clearChatHistory } from '$lib/stores/ui.js';
	import { isGenerating, currentStage } from '$lib/stores/generation.js';
	import { scene as sceneStore, meshes } from '$lib/stores/scene.js';
	import { get } from 'svelte/store';
	import { browser } from '$app/environment';
	import { generateScene, modifyScene, clearScene } from '$lib/scene/generator.js';
	import ImageRender from './ImageRender.svelte';
	import SceneContext from './SceneContext.svelte';
	import ActionBlock from './ActionBlock.svelte';

	// Tab state
	let activeTab = 'chat'; // 'chat', 'examples', 'params', 'scene', or 'render'

	// ImageRender component ref
	let imageRenderRef;

	// Examples data
	let examples = [];
	let examplesLoading = true;

	// Chat state
	let chatInput = '';
	let chatTextarea;
	let chatContainer;
	let hasGeneratedScene = false;

	// Scene controls state
	let backgroundColor = '#ffffff';
	let lightIntensity = 1.0;
	let gridVisible = true;
	let shadowsEnabled = true;
	let ambientLightIntensity = 0.6;
	let wireframeMode = false;

	onMount(async () => {
		if (!browser) return;

		// Load examples
		const { ensureModulesLoaded } = await import('$lib/core/index.js');
		await ensureModulesLoaded();

		const RegistryClass = window.ExampleRegistry;
		if (RegistryClass) {
			const registry = new RegistryClass();
			await registry.load();
			window.exampleRegistry = registry;
			examples = registry.index || [];
			examplesLoading = false;
		}

	});

	function togglePanel() {
		showSidePanel.update(v => !v);
	}

	function setTab(tab) {
		activeTab = tab;
		if (tab === 'chat') {
			setTimeout(() => scrollToBottom(), 50);
		} else if (tab === 'render') {
			setTimeout(() => { if (imageRenderRef) imageRenderRef.generatePromptFromHistory(); }, 50);
		}
	}

	// ===== EXAMPLES FUNCTIONS =====
	async function loadExample(example) {
		console.log('Loading example:', example.id);
		if (!window.exampleRegistry) return;

		const data = window.exampleRegistry.getById(example.id);
		if (!data || !data.graph) {
			console.error('Example not found or has no graph:', example.id);
			return;
		}

		const { scene: sceneStore, meshes } = await import('$lib/stores/scene.js');
		const { addLog } = await import('$lib/stores/ui.js');
		const { get } = await import('svelte/store');

		const { ensureSceneModulesLoaded } = await import('$lib/scene/index.js');
		await ensureSceneModulesLoaded();

		const threeScene = get(sceneStore);
		if (threeScene && window.SceneCore?.manager?.clearScene) {
			window.SceneCore.manager.clearScene({ scene: threeScene, log: addLog });
			meshes.set([]);
		}

		if (threeScene && window.SceneCore?.executor?.executeScene) {
			const result = window.SceneCore.executor.executeScene(
				[data.graph],
				null,
				{ scene: threeScene, THREE: window.THREE, ActionRegistry: window.ActionRegistry }
			);
			meshes.set(result?.meshes || []);
			addLog(`Loaded example "${example.name}": ${result?.meshCount || 0} meshes`, 'success');
			currentChain.set([data.graph]);
			setTab('params'); // Use setTab to properly initialize params
		}
	}


	// ===== PARAMS TAB HELPERS =====

	function isColorParam(key) {
		return key === 'color' || key.toLowerCase().endsWith('color');
	}

	function getVariableDescription(key) {
		const descriptions = {
			// Common material properties
			'color': 'Material color of the object',
			'metalness': 'How metallic the surface appears (0=non-metallic, 1=fully metallic)',
			'roughness': 'Surface roughness (0=smooth/mirror-like, 1=rough/diffuse)',
			'opacity': 'Transparency of the material (0=invisible, 1=fully opaque)',
			'transparent': 'Whether the material supports transparency',
			
			// Common dimensions
			'width': 'Width along the X-axis',
			'height': 'Height along the Y-axis', 
			'depth': 'Depth along the Z-axis',
			'radius': 'Radius of circular shapes',
			'thickness': 'Thickness of walls or surfaces',
			'size': 'General size multiplier',
			
			// Common positioning
			'x': 'Position along the X-axis',
			'y': 'Position along the Y-axis',
			'z': 'Position along the Z-axis',
			
			// Common geometry properties
			'segments': 'Number of segments for smooth curves',
			'detail': 'Level of geometric detail',
			'smooth': 'Whether to smooth the surface',
			
			// Common patterns
			'count': 'Number of items to create',
			'spacing': 'Distance between items',
			'scale': 'Scale factor for size',
			'rotation': 'Rotation angle in degrees',
			'angle': 'Angle in degrees'
		};
		
		// Check for exact match first
		if (descriptions[key]) return descriptions[key];
		
		// Check for partial matches (e.g., "width" matches "beamWidth")
		const lowerKey = key.toLowerCase();
		for (const [pattern, desc] of Object.entries(descriptions)) {
			if (lowerKey.includes(pattern.toLowerCase())) {
				return desc;
			}
		}
		
		return null;
	}

	function valToHex(val) {
		if (typeof val === 'number') return '#' + Math.round(val).toString(16).padStart(6, '0');
		if (typeof val === 'string') {
			if (/^#[0-9a-fA-F]{3,8}$/.test(val)) return val;
			try { const ctx = document.createElement('canvas').getContext('2d'); ctx.fillStyle = val; return ctx.fillStyle; } catch { return '#888888'; }
		}
		return '#888888';
	}

	// ===== CHAIN DRAFT (live editable copy of currentChain — always an array) =====

	let chainDraft = null;
	$: if ($currentChain) {
		const arr = Array.isArray($currentChain) ? $currentChain : [$currentChain];
		chainDraft = JSON.parse(JSON.stringify(arr));
	}

	// ===== ACTION VISIBILITY TRACKING =====
	let actionVisibility = {};

	function updateSceneVisibility() {
		const threeScene = get(sceneStore);
		if (!threeScene) return;
		
		let updatedCount = 0;
		threeScene.traverse((child) => {
			if ((child.isMesh || child.isLine || child.isLineLoop) && child.userData) {
				const meta = child.userData;
				const key = `${meta.objectIndex}-${meta.actionIndex}`;
				const shouldBeVisible = actionVisibility[key] !== false;
				if (child.visible !== shouldBeVisible) {
					child.visible = shouldBeVisible;
					updatedCount++;
				}
			}
		});
		
		if (updatedCount > 0) {
			addLog(`Updated visibility for ${updatedCount} meshes`, 'info');
		}
	}

	// Initialize visibility state when chainDraft changes
	$: if (chainDraft) {
		const newVisibility = { ...actionVisibility };
		chainDraft.forEach((obj, objIdx) => {
			if (obj.actions) {
				obj.actions.forEach((action, actionIdx) => {
					const key = `${objIdx}-${actionIdx}`;
					// Only set if not already set (preserve user toggles)
					if (!(key in newVisibility)) {
						// Default to action.visible property, or true if not specified
						newVisibility[key] = action.visible !== false;
					}
				});
			}
		});
		actionVisibility = newVisibility;
		
		// Expose to window for executor to access
		if (typeof window !== 'undefined') {
			window.actionVisibility = actionVisibility;
		}
		
		// Update scene to reflect new visibility state
		updateSceneVisibility();
	}

	function toggleActionVisibility(objIdx, actionIdx) {
		const key = `${objIdx}-${actionIdx}`;
		const currentStored = actionVisibility[key];
		const isVisible = currentStored !== false;
		const newVisibility = !isVisible;
		
		addLog(`Toggle ${objIdx}-${actionIdx}: stored=${currentStored}, wasVisible=${isVisible}, setTo=${newVisibility}`, 'info');
		
		// Update visibility state (trigger reactivity)
		actionVisibility = { ...actionVisibility, [key]: newVisibility };
		
		// Keep window in sync for executor
		if (typeof window !== 'undefined') {
			window.actionVisibility = actionVisibility;
		}
		
		const threeScene = get(sceneStore);
		if (!threeScene) {
			addLog('Scene not available', 'warning');
			return;
		}
		
		let toggledCount = 0;
		// Find meshes with matching metadata
		threeScene.traverse((child) => {
			if ((child.isMesh || child.isLine || child.isLineLoop) && child.userData) {
				const meta = child.userData;
				if (meta.objectIndex === objIdx && meta.actionIndex === actionIdx) {
					const wasVisible = child.visible;
					child.visible = newVisibility;
					addLog(`Mesh ${objIdx}-${actionIdx}: ${wasVisible} -> ${newVisibility}`, 'info');
					toggledCount++;
				}
			}
		});
		
		if (toggledCount > 0) {
			addLog(`Action ${actionIdx + 1} ${newVisibility ? 'shown' : 'hidden'} (${toggledCount} mesh${toggledCount > 1 ? 'es' : ''})`, 'info');
		} else {
			addLog(`No meshes found for action ${actionIdx + 1}`, 'warning');
		}
	}

	$: isActionVisible = (objIdx, actionIdx) => {
		const key = `${objIdx}-${actionIdx}`;
		return actionVisibility[key] !== false;
	};

	function applyParams() {
		if (!chainDraft?.length) return;
		const threeScene = get(sceneStore);
		if (!threeScene) { addLog('Scene not available', 'error'); return; }
		clearScene();
		const simItem = chainDraft.find(o => o._simulationConfig);
		if (simItem) {
			const executeSimulationArrangement = window.SceneCore?.executor?.executeSimulationArrangement;
			if (!executeSimulationArrangement) { addLog('Simulation executor not available', 'error'); return; }
			const reg = window.ActionRegistry;
			const templateGraphs = chainDraft.map(g => {
				if (!reg?.get || !g.actions?.length) return g;
				const cleaned = g.actions.filter(a => {
					if (!a?.op) return true;
					const cat = reg.get(a.op)?.category;
					return cat !== 'deformer';
				});
				return { ...g, actions: cleaned.length ? cleaned : g.actions.slice(0, 1) };
			});
			const result = executeSimulationArrangement(
				templateGraphs, simItem._simulationConfig,
				{ scene: threeScene, THREE: window.THREE, ActionRegistry: window.ActionRegistry }
			);
			currentChain.set(chainDraft);
			addLog(`Simulation applied: ${result?.instanceCount || 0} instances`, 'success');
		} else {
			const executeScene = window.SceneCore?.executor?.executeScene;
			if (!executeScene) { addLog('Executor not available', 'error'); return; }
			const result = executeScene(
				chainDraft, null,
				{ scene: threeScene, THREE: window.THREE, ActionRegistry: window.ActionRegistry }
			);
			currentChain.set(chainDraft.map(o => ({
				id: o.id, name: o.name, mode: o.mode,
				vars: o.vars, actions: o.actions, transform: o.transform
			})));
			addLog(`Params applied: ${result?.meshCount || 0} meshes`, 'success');
		}
	}

	function resetParams() {
		const arr = Array.isArray($currentChain) ? $currentChain : [$currentChain];
		chainDraft = JSON.parse(JSON.stringify(arr));
	}

	// ===== CHAT FUNCTIONS =====
	function scrollToBottom() {
		if (chatContainer) {
			chatContainer.scrollTop = chatContainer.scrollHeight;
		}
	}

	function handleChatInput(e) {
		const target = e.target;
		target.style.height = 'auto';
		target.style.height = Math.min(target.scrollHeight, 100) + 'px';
	}

	function handleChatKeyPress(e) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			sendChatMessage();
		}
	}

	async function sendChatMessage() {
		if (!chatInput.trim() || $isGenerating) return;

		const message = chatInput.trim();
		addChatMessage('user', message);
		chatInput = '';
		if (chatTextarea) chatTextarea.style.height = 'auto';
		setTimeout(() => scrollToBottom(), 50);

		isGenerating.set(true);
		currentStage.set('Processing request...');

		try {
			if (!hasGeneratedScene) {
				// First generation - create new scene
				await generateScene(message);
				hasGeneratedScene = true;
			} else {
				// Follow-up - modify existing scene
				await modifyScene(message, get(currentChain), get(chatHistory));
			}
			addChatMessage('assistant', 'Done! Check the 3D view for updates.');
		} catch (error) {
			addLog(`Chat request failed: ${error.message}`, 'error');
			addChatMessage('assistant', `Error: ${error.message}`, { error: true });
		} finally {
			isGenerating.set(false);
			currentStage.set('');
			setTimeout(() => scrollToBottom(), 50);
		}
	}

	function clearChat() {
		clearChatHistory();
		hasGeneratedScene = false;
	}

	function startNewChat() {
		clearChat();
		chatInput = '';
		if (chatTextarea) chatTextarea.style.height = 'auto';
	}

	function editAndResendMessage(index) {
		const history = get(chatHistory);
		const messageToEdit = history[index];
		if (messageToEdit && messageToEdit.role === 'user') {
			// Remove messages from this point onward
			chatHistory.update(h => h.slice(0, index));
			// Set the message content to input
			chatInput = messageToEdit.content;
			// Adjust hasGeneratedScene based on remaining history
			const remainingHistory = get(chatHistory);
			hasGeneratedScene = remainingHistory.some(m => m.role === 'assistant' && !m.metadata?.error);
			// Focus textarea
			setTimeout(() => {
				if (chatTextarea) {
					chatTextarea.focus();
					chatTextarea.style.height = 'auto';
					chatTextarea.style.height = Math.min(chatTextarea.scrollHeight, 100) + 'px';
				}
			}, 50);
		}
	}

	// ===== SCENE CONTROLS FUNCTIONS =====
	function updateBackgroundColor() {
		const threeScene = get(sceneStore);
		if (threeScene) {
			threeScene.background = new window.THREE.Color(backgroundColor);
			addLog(`Background color set to ${backgroundColor}`, 'info');
		}
	}

	function updateGridVisibility() {
		const threeScene = get(sceneStore);
		if (threeScene) {
			// Find grid helper by traversing scene
			threeScene.traverse((child) => {
				if (child.type === 'GridHelper') {
					child.visible = gridVisible;
				}
			});
		}
		addLog(`Grid helper ${gridVisible ? 'visible' : 'hidden'}`, 'info');
	}

	function updateLightIntensity() {
		const threeScene = get(sceneStore);
		if (threeScene) {
			// Find and update directional light
			threeScene.traverse((child) => {
				if (child.type === 'DirectionalLight') {
					child.intensity = lightIntensity;
				}
			});
		}
	}

	function updateAmbientLightIntensity() {
		const threeScene = get(sceneStore);
		if (threeScene) {
			// Find and update ambient light
			threeScene.traverse((child) => {
				if (child.type === 'AmbientLight') {
					child.intensity = ambientLightIntensity;
				}
			});
		}
	}

	function updateShadows() {
		const threeScene = get(sceneStore);
		if (threeScene) {
			threeScene.traverse((child) => {
				if (child.type === 'DirectionalLight') {
					child.castShadow = shadowsEnabled;
				}
				if (child.isMesh) {
					child.castShadow = shadowsEnabled;
					child.receiveShadow = shadowsEnabled;
				}
			});
			// Update renderer shadow map setting if available
			if (window.SceneCore?.renderer) {
				window.SceneCore.renderer.shadowMap.enabled = shadowsEnabled;
				window.SceneCore.renderer.shadowMap.needsUpdate = true;
			}
		}
		addLog(`Shadows ${shadowsEnabled ? 'enabled' : 'disabled'}`, 'info');
	}

	function updateWireframeMode() {
		const threeScene = get(sceneStore);
		if (threeScene) {
			threeScene.traverse((child) => {
				if (child.isMesh && child.material) {
					// Handle both single materials and arrays of materials
					if (Array.isArray(child.material)) {
						child.material.forEach(mat => {
							if (mat) mat.wireframe = wireframeMode;
						});
					} else {
						child.material.wireframe = wireframeMode;
					}
				}
				// Skip Line objects - they don't have wireframe mode
			});
		}
		addLog(`Wireframe mode ${wireframeMode ? 'enabled' : 'disabled'}`, 'info');
	}

	function resetCamera() {
		if (window.SceneCore?.camera && window.SceneCore?.controls) {
			window.SceneCore.camera.position.set(5, 5, 5);
			window.SceneCore.camera.lookAt(0, 0, 0);
			window.SceneCore.controls.target.set(0, 0, 0);
			window.SceneCore.controls.update();
			addLog('Camera reset to default view', 'info');
		}
	}

	function fitCameraToScene() {
		const threeScene = get(sceneStore);
		if (threeScene && window.SceneCore?.camera && window.SceneCore?.controls) {
			const box = new window.THREE.Box3().setFromObject(threeScene);
			const center = box.getCenter(new window.THREE.Vector3());
			const size = box.getSize(new window.THREE.Vector3());
			const maxDim = Math.max(size.x, size.y, size.z);
			const distance = maxDim * 1.5;

			window.SceneCore.camera.position.set(center.x + distance, center.y + distance, center.z + distance);
			window.SceneCore.camera.lookAt(center);
			window.SceneCore.controls.target.copy(center);
			window.SceneCore.controls.update();
			addLog('Camera fitted to scene bounds', 'info');
		}
	}
</script>

{#if $showSidePanel}
	<!-- Main Panel -->
	<div class="side-panel">
		<div class="panel-header">
			<div class="tabs">
				<button
					class="tab-btn"
					class:active={activeTab === 'chat'}
					on:click={() => setTab('chat')}
				>
					Chat
				</button>
				<button
					class="tab-btn"
					class:active={activeTab === 'examples'}
					on:click={() => setTab('examples')}
				>
					Examples
				</button>
				<button
					class="tab-btn"
					class:active={activeTab === 'params'}
					on:click={() => setTab('params')}
				>
					Parameters
				</button>
				<button
					class="tab-btn"
					class:active={activeTab === 'scene'}
					on:click={() => setTab('scene')}
				>
					Scene
				</button>
				<button
					class="tab-btn"
					class:active={activeTab === 'render'}
					on:click={() => setTab('render')}
				>
					Render
				</button>
			</div>
			<button class="close-btn" on:click={togglePanel}>✕</button>
		</div>

		<div class="panel-content">
			{#if activeTab === 'chat'}
				<div class="tab-content chat-tab">
					<SceneContext />
					
					<!-- Prompt Guidance Section -->
					<details class="obj-block">
						<summary class="obj-header">
							<span class="obj-name">Prompting Best Practices</span>
							<span class="obj-badge">Guide</span>
						</summary>
						<div class="context-fields">
							<div class="guidance-section">
								<h4>Be Specific & Structural</h4>
								<p>Describe structural roles and relationships rather than exact dimensions:</p>
								<div class="guidance-examples">
									<div class="example-good">Yes: "A table with four legs supporting a flat surface"</div>
									<div class="example-bad">No: "A table 120cm x 80cm x 75cm"</div>
								</div>
							</div>
							
							<div class="guidance-section">
								<h4>Use Relational Positioning</h4>
								<p>Describe how parts connect rather than coordinates:</p>
								<div class="guidance-examples">
									<div class="example-good">Yes: "Stack boxes on top of each other"</div>
									<div class="example-bad">No: "Box at y=5, second box at y=10"</div>
								</div>
							</div>
							
							<div class="guidance-section">
								<h4>Focus on Function & Form</h4>
								<p>Use structural-role language that works for any object type:</p>
								<div class="guidance-examples">
									<div class="example-good">Yes: "Vertical supports with horizontal spanning elements"</div>
									<div class="example-bad">No: "Gothic arches with flying buttresses"</div>
								</div>
							</div>
							
							<div class="guidance-section">
								<h4>Describe Patterns Clearly</h4>
								<p>For repetition, specify count and arrangement:</p>
								<div class="guidance-examples">
									<div class="example-good">Yes: "Create 5 pillars evenly spaced in a row"</div>
									<div class="example-bad">No: "Repeat with spacing 2.5 units"</div>
								</div>
							</div>
							
							<div class="guidance-section">
								<h4>Material & Style</h4>
								<p>Specify materials and aesthetic qualities separately from structure:</p>
								<div class="guidance-examples">
									<div class="example-good">Yes: "Wooden chair with curved legs, polished surface"</div>
									<div class="example-bad">No: "Chair with wood texture and brown color"</div>
								</div>
							</div>
							
							<div class="guidance-tips">
								<h4>Pro Tips</h4>
								<ul>
									<li>Start simple, then modify in follow-up messages</li>
									<li>Use "stack on top", "attach to", "surround" for positioning</li>
									<li>Describe load-bearing vs decorative elements</li>
									<li>Specify "hollow", "solid", "thin", "thick" for geometry hints</li>
								</ul>
							</div>
						</div>
					</details>
					
					<div class="chat-messages" bind:this={chatContainer}>
						{#if $chatHistory.length === 0}
							<div class="chat-welcome">
								<div class="welcome-title">👋 Welcome to SpellShape</div>
								<div class="welcome-text">Describe any 3D object or scene and I'll generate it for you.<br><br>Examples:</div>
								<div class="welcome-examples">
									<button class="example-chip" on:click={() => { chatInput = 'A wooden chair with curved legs'; sendChatMessage(); }}>A wooden chair</button>
									<button class="example-chip" on:click={() => { chatInput = 'A modern glass table'; sendChatMessage(); }}>Glass table</button>
									<button class="example-chip" on:click={() => { chatInput = 'A tower with multiple tiers'; sendChatMessage(); }}>Tiered tower</button>
								</div>
							</div>
						{:else}
							{#each $chatHistory as message, index}
								<div class="chat-message-wrapper {message.role}">
									<div class="chat-message {message.role}" class:error={message.metadata?.error}>
										<div class="message-header">
											<span class="role">{message.role === 'user' ? 'You' : 'Spellshape AI'}</span>
											{#if message.role === 'user'}
												<button class="edit-btn" on:click={() => editAndResendMessage(index)} title="Edit and resend">
													<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
												</button>
											{/if}
										</div>
										<div class="message-content">{message.content}</div>
									</div>
								</div>
							{/each}
							{#if $isGenerating}
								<div class="chat-message-wrapper assistant">
									<div class="chat-message assistant generating">
										<div class="message-header">
											<span class="role">Spellshape AI</span>
											<span class="typing">typing...</span>
										</div>
										{#if $currentStage}
											<div class="stage-indicator">{$currentStage}</div>
										{/if}
									</div>
								</div>
							{/if}
						{/if}
					</div>

					<div class="chat-input-area">
						<textarea
							bind:this={chatTextarea}
							bind:value={chatInput}
							on:keypress={handleChatKeyPress}
							on:input={handleChatInput}
							rows="1"
							placeholder={hasGeneratedScene ? 'Ask to modify colors, shapes, or rebuild...' : 'Describe your 3D scene...'}
							disabled={$isGenerating}
						></textarea>
						{#if $isGenerating}
							<div class="chat-loading">
								<div class="spinner"></div>
							</div>
						{:else}
							<button class="send-btn" on:click={sendChatMessage} disabled={$isGenerating || !chatInput.trim()} title="Send">
								<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
							</button>
						{/if}
					</div>
				</div>
			{:else if activeTab === 'examples'}
				<div class="tab-content">
					{#if examplesLoading}
						<div class="loading">Loading examples...</div>
					{:else}
						<div class="examples-list">
							{#each examples as example}
								<button class="example-item" on:click={() => loadExample(example)}>
									<div class="example-name">{example.name}</div>
									<div class="example-desc">{example.description || ''}</div>
								</button>
							{/each}
						</div>
					{/if}
				</div>
			{:else if activeTab === 'params'}
				<!-- Params tab — one accordion per scene object -->
				<div class="tab-content params-tab">
					{#if !chainDraft?.length}
						<div class="params-empty">
							<div class="params-empty-icon">⚙️</div>
							<p>Generate a scene first to see its parameters.</p>
						</div>
					{:else}
						{#each chainDraft as obj, ci}
							<details class="obj-block" open>
								<summary class="obj-header">
									<span class="obj-name">{obj.name}</span>
									<span class="obj-badge">{obj.actions?.length || 0} actions</span>
								</summary>

								{#if obj.transform?.position}
									<details class="section-block">
										<summary class="section-header">Position</summary>
										<div class="vars-grid">
											{#each ['x','y','z'] as axis}
												<div class="var-row">
													<div class="var-label-section">
														<label class="var-key" for="pos-{ci}-{axis}">{axis.toUpperCase()}</label>
														<div class="var-desc">Position along {axis.toUpperCase()}-axis</div>
													</div>
													<input id="pos-{ci}-{axis}" class="pi pi-num" type="text" inputmode="decimal"
														bind:value={chainDraft[ci].transform.position[axis]} step="0.1" />
												</div>
											{/each}
										</div>
									</details>
								{/if}

								{#if obj.vars && Object.keys(obj.vars).length > 0}
									<details class="section-block" open>
										<summary class="section-header">Variables <span class="count-badge">{Object.keys(obj.vars).length}</span></summary>
										<div class="vars-grid">
											{#each Object.entries(obj.vars) as [key, val]}
												<div class="var-row">
													<div class="var-label-section">
														<label class="var-key">{key}</label>
														{#if getVariableDescription(key)}
															<div class="var-desc">{getVariableDescription(key)}</div>
														{/if}
													</div>
													{#if isColorParam(key)}
														<div class="pi-color-wrap">
															<input class="pi pi-color" type="color"
																value={valToHex(chainDraft[ci].vars[key])}
																on:change={e => { chainDraft[ci].vars[key] = e.target.value; chainDraft = chainDraft; }} />
															<span class="pi-color-label">{chainDraft[ci].vars[key]}</span>
														</div>
													{:else if typeof val === 'number'}
														<input class="pi pi-num" type="text" inputmode="decimal" bind:value={chainDraft[ci].vars[key]} />
													{:else}
														<input class="pi pi-str" type="text" bind:value={chainDraft[ci].vars[key]} />
													{/if}
												</div>
											{/each}
										</div>
									</details>
								{/if}

								{#if obj.actions?.length > 0}
									<details class="section-block" open>
										<summary class="section-header">Actions <span class="count-badge">{obj.actions.length}</span></summary>
										<div class="actions-list">
											{#each obj.actions as action, ai}
												<ActionBlock
													{action}
													actionIdx={ai}
													isVisible={isActionVisible(ci, ai)}
													onVisibilityToggle={() => toggleActionVisibility(ci, ai)}
													onParamChange={(key, val) => {
														if (!chainDraft[ci].actions[ai].params) chainDraft[ci].actions[ai].params = {};
														chainDraft[ci].actions[ai].params[key] = val;
														chainDraft = chainDraft;
													}}
													onAsChange={(val) => {
														chainDraft[ci].actions[ai].as = val;
														chainDraft = chainDraft;
													}}
												/>
											{/each}
										</div>
									</details>
								{/if}

								{#if obj._simulationConfig}
									<details class="section-block" open>
										<summary class="section-header">Arrangement: {obj._simulationConfig.name} <span class="count-badge">scene</span></summary>
										<div class="vars-grid">
											{#if obj._simulationConfig.params.strategy}
												<div class="var-row">
													<div class="var-label-section">
														<label class="var-key">Pattern</label>
														<div class="var-desc">Distribution pattern for instances</div>
													</div>
													<select class="pi pi-select" bind:value={chainDraft[ci]._simulationConfig.params.strategy}>
														<option value="poisson">Scattered (Natural)</option>
														<option value="random">Random</option>
														<option value="grid">Grid</option>
														<option value="uniform">Uniform</option>
														<option value="clustered">Clustered</option>
													</select>
												</div>
											{/if}
											{#if obj._simulationConfig.params.count !== undefined}
												<div class="var-row">
													<div class="var-label-section">
														<label class="var-key">Count: {chainDraft[ci]._simulationConfig.params.count}</label>
														<div class="var-desc">Number of instances to generate</div>
													</div>
													<input class="pi pi-slider" type="range" min="1" max="100"
														bind:value={chainDraft[ci]._simulationConfig.params.count} />
												</div>
											{/if}
											{#if obj._simulationConfig.params.minDistance !== undefined}
												<div class="var-row">
													<div class="var-label-section">
														<label class="var-key">Spacing: {chainDraft[ci]._simulationConfig.params.minDistance.toFixed(2)}</label>
														<div class="var-desc">Minimum distance between instances</div>
													</div>
													<input class="pi pi-slider" type="range" min="0.1" max="5" step="0.1"
														bind:value={chainDraft[ci]._simulationConfig.params.minDistance} />
												</div>
											{/if}
											{#if obj._simulationConfig.params.extent !== undefined}
												<div class="var-row">
													<div class="var-label-section">
														<label class="var-key">Area: {chainDraft[ci]._simulationConfig.params.extent.toFixed(1)}</label>
														<div class="var-desc">Area size for distribution</div>
													</div>
													<input class="pi pi-slider" type="range" min="1" max="20" step="0.5"
														bind:value={chainDraft[ci]._simulationConfig.params.extent} />
												</div>
											{/if}
											{#each Object.entries(obj._simulationConfig.params || {}) as [key, val]}
												{#if !['strategy', 'count', 'minDistance', 'extent'].includes(key)}
													<div class="var-row">
														<div class="var-label-section">
															<label class="var-key">{key}</label>
															{#if getVariableDescription(key)}
																<div class="var-desc">{getVariableDescription(key)}</div>
															{/if}
														</div>
														{#if typeof val === 'number'}
															<input class="pi pi-num" type="text" inputmode="decimal"
																bind:value={chainDraft[ci]._simulationConfig.params[key]} />
														{:else if typeof val === 'boolean'}
															<input type="checkbox" bind:checked={chainDraft[ci]._simulationConfig.params[key]} />
														{:else}
															<input class="pi pi-str" type="text" bind:value={chainDraft[ci]._simulationConfig.params[key]} />
														{/if}
													</div>
												{/if}
											{/each}
										</div>
									</details>
								{/if}
							</details>
						{/each}
						<div class="params-actions">
							<button class="params-apply-btn" on:click={applyParams}>Apply</button>
							<button class="params-reset-btn" on:click={resetParams}>Reset</button>
						</div>
					{/if}
				</div>
			{:else if activeTab === 'scene'}
				<div class="tab-content scene-tab">
					<div class="scene-controls">
						<details class="scene-section" open>
							<summary class="section-header">Environment</summary>
							<div class="scene-control-row">
								<label class="scene-label">Background</label>
								<div class="scene-color-wrap">
									<input class="scene-color" type="color" bind:value={backgroundColor} on:change={updateBackgroundColor} />
									<span class="scene-color-label">{backgroundColor}</span>
								</div>
							</div>
							<div class="scene-control-row">
								<label class="scene-label">Grid Helper</label>
								<label class="toggle-switch">
									<input type="checkbox" bind:checked={gridVisible} on:change={updateGridVisibility} />
									<span class="toggle-slider"></span>
								</label>
							</div>
							<div class="scene-control-row">
								<label class="scene-label">Wireframe</label>
								<label class="toggle-switch">
									<input type="checkbox" bind:checked={wireframeMode} on:change={updateWireframeMode} />
									<span class="toggle-slider"></span>
								</label>
							</div>
						</details>

						<details class="scene-section" open>
							<summary class="section-header">Lighting</summary>
							<div class="scene-control-row">
								<label class="scene-label">Main Light</label>
								<input class="scene-slider" type="range" min="0" max="2" step="0.1" bind:value={lightIntensity} on:input={updateLightIntensity} />
								<span class="scene-value">{lightIntensity.toFixed(1)}</span>
							</div>
							<div class="scene-control-row">
								<label class="scene-label">Ambient Light</label>
								<input class="scene-slider" type="range" min="0" max="1" step="0.1" bind:value={ambientLightIntensity} on:input={updateAmbientLightIntensity} />
								<span class="scene-value">{ambientLightIntensity.toFixed(1)}</span>
							</div>
							<div class="scene-control-row">
								<label class="scene-label">Shadows</label>
								<label class="toggle-switch">
									<input type="checkbox" bind:checked={shadowsEnabled} on:change={updateShadows} />
									<span class="toggle-slider"></span>
								</label>
							</div>
						</details>

						<details class="scene-section">
							<summary class="section-header">Camera</summary>
							<div class="scene-control-row">
								<button class="scene-btn" on:click={resetCamera}>Reset View</button>
								<button class="scene-btn" on:click={fitCameraToScene}>Fit to Scene</button>
							</div>
						</details>
					</div>
				</div>
			{:else if activeTab === 'render'}
				<div class="tab-content render-tab">
					<ImageRender bind:this={imageRenderRef} {addLog} />
				</div>
			{/if}
		</div>
	</div>
{/if}

<!-- Floating Toggle Button (when panel is closed) -->
{#if !$showSidePanel}
	<button class="floating-toggle" on:click={togglePanel} title="Open Panel">
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
			<path d="M4 6h16M4 12h16M4 18h16"/>
		</svg>
	</button>
{/if}

<style>
	/* CSS Variables for Design System */
	:root {
		/* Primary Colors */
		--primary-blue: #0000eb;
		--primary-blue-hover: #0000c9;
		--primary-blue-light: rgba(0, 0, 235, 0.08);
		--primary-blue-light-hover: rgba(0, 0, 235, 0.15);
		--primary-blue-border: rgba(0, 0, 235, 0.15);
		--primary-blue-border-hover: rgba(0, 0, 235, 0.25);
		
		/* Text Colors */
		--text-primary: #1a1a1a;
		--text-secondary: #333;
		--text-muted: #666;
		--text-light: #888;
		--text-lighter: #999;
		--text-hint: #aaa;
		--text-dim: #555;
		--text-dimmer: #777;
		
		/* Background Colors */
		--bg-primary: rgba(255, 255, 255, 0.6);
		--bg-secondary: rgba(255, 255, 255, 0.9);
		--bg-tertiary: rgba(255, 255, 255, 0.95);
		--bg-panel: rgba(255, 255, 255, 0.5);
		--bg-input: rgba(255, 255, 255, 0.8);
		--bg-hover: rgba(255, 255, 255, 0.9);
		--bg-subtle: rgba(0, 0, 0, 0.02);
		--bg-subtle-hover: rgba(0, 0, 0, 0.04);
		--bg-subtle-light: rgba(0, 0, 0, 0.06);
		--bg-subtle-lighter: rgba(0, 0, 0, 0.08);
		--bg-subtle-lightest: rgba(0, 0, 0, 0.1);
		--bg-error: rgba(235, 0, 0, 0.08);
		
		/* Border Colors */
		--border-primary: rgba(0, 0, 0, 0.08);
		--border-secondary: rgba(0, 0, 0, 0.06);
		--border-light: rgba(0, 0, 0, 0.05);
		--border-lighter: rgba(0, 0, 0, 0.1);
		--border-input: rgba(0, 0, 0, 0.12);
		--border-focus: #667eea;
		--border-error: rgba(235, 0, 0, 0.15);
		
		/* Spacing */
		--spacing-xs: 2px;
		--spacing-sm: 4px;
		--spacing-md: 6px;
		--spacing-lg: 8px;
		--spacing-xl: 10px;
		--spacing-2xl: 12px;
		--spacing-3xl: 16px;
		--spacing-4xl: 20px;
		
		/* Border Radius */
		--radius-sm: 3px;
		--radius-md: 4px;
		--radius-lg: 6px;
		--radius-xl: 8px;
		--radius-2xl: 10px;
		--radius-3xl: 12px;
		--radius-full: 50%;
		
		/* Typography */
		--font-xs: 8px;
		--font-sm: 9px;
		--font-base: 10px;
		--font-md: 11px;
		--font-lg: 12px;
		--font-xl: 13px;
		--font-2xl: 14px;
		--font-3xl: 16px;
		
		/* Shadows */
		--shadow-panel: 0 0 12px rgba(255, 255, 255, 0.9), 0 0 8px rgba(255, 255, 255, 0.9), 0 0 4px rgba(255, 255, 255, 0.9);
		--shadow-hover: 0 4px 12px rgba(0, 0, 0, 0.08);
	}

	.side-panel {
		position: fixed;
		top: var(--spacing-3xl);
		left: var(--spacing-3xl);
		width: 380px;
		height: calc(100vh - 32px);
		max-height: calc(100vh - 32px);
		background: var(--bg-panel);
		backdrop-filter: blur(30px);
		-webkit-backdrop-filter: blur(20px);
		border-radius: var(--radius-3xl);
		border: 1px solid rgba(255, 255, 255, 0.4);
		box-shadow: var(--shadow-panel);
		display: flex;
		flex-direction: column;
		z-index: 200;
		overflow: visible;
	}

	.panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--spacing-2xl) var(--spacing-3xl);
		border-bottom: 1px solid var(--border-primary);
		background: rgba(255, 255, 255, 0.4);
		position: relative;
	}

	.tabs {
		display: flex;
		gap: var(--spacing-sm);
		overflow-x: auto;
		scrollbar-width: none;
		-ms-overflow-style: none;
		flex: 1;
		margin-right: var(--spacing-lg);
	}

	.tabs::-webkit-scrollbar {
		display: none;
	}

	.tab-btn {
		background: transparent;
		border: none;
		padding: var(--spacing-lg) var(--spacing-xl);
		border-radius: 0;
		font-size: var(--font-lg);
		font-weight: 500;
		color: var(--text-muted);
		cursor: pointer;
		transition: all 0.2s;
		position: relative;
		white-space: nowrap;
		flex-shrink: 0;
	}

	.tab-btn:hover {
		color: var(--text-secondary);
	}

	.tab-btn.active {
		color: var(--primary-blue);
	}

	.tab-btn.active::after {
		content: '';
		position: absolute;
		bottom: 0;
		left: var(--spacing-lg);
		right: var(--spacing-lg);
		height: 3px;
		background: var(--primary-blue);
		border-radius: var(--radius-sm);
	}

	.close-btn {
		position: absolute;
		right: -32px;
		top: var(--spacing-3xl);
		background: white;
		/* border: 1px solid var(--primary-blue);
		border-left: none; */
		border: none;
		width: 32px;
		height: 44px;
		border-radius: 0 var(--radius-xl) var(--radius-xl) 0;
		font-size: var(--font-2xl);
		color: var(--primary-blue);
		cursor: pointer;
		transition: background 0.2s;
		display: flex;
		align-items: center;
		justify-content: center;
		font-weight: 300;
		/* box-shadow: 2px 2px 8px rgba(0, 0, 0, 0.15); */
		z-index: 201;
	}

	.close-btn:hover {
		background: #0000eb10;
	}

	.panel-content {
		flex: 1;
		overflow-y: auto;
		padding: var(--spacing-3xl);
		min-height: 0;
		border-radius: 0 0 var(--radius-3xl) var(--radius-3xl);
	}

	.panel-content::-webkit-scrollbar {
		width: 6px;
	}

	.panel-content::-webkit-scrollbar-track {
		background: transparent;
	}

	.panel-content::-webkit-scrollbar-thumb {
		background: rgba(0, 0, 0, 0.15);
		border-radius: 3px;
	}

	.loading {
		text-align: center;
		padding: 40px;
		color: var(--text-lighter);
		font-size: var(--font-xl);
	}

	/* Examples Tab */
	.examples-list {
		display: flex;
		flex-direction: column;
		gap: var(--spacing-lg);
	}

	.example-item {
		background: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-2xl);
		padding: var(--spacing-2xl) var(--spacing-xl);
		text-align: left;
		cursor: pointer;
		transition: all 0.2s;
	}

	.example-item:hover {
		background: var(--bg-hover);
		border-color: var(--border-lighter);
		transform: translateY(-1px);
		box-shadow: var(--shadow-hover);
	}

	.example-name {
		font-weight: 500;
		font-size: var(--font-xl);
		color: var(--text-primary);
		margin-bottom: var(--spacing-sm);
	}

	.example-desc {
		font-size: var(--font-lg);
		color: var(--text-light);
		line-height: 1.4;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	/* Params Tab */
	.params-toolbar {
		display: flex;
		gap: 8px;
		margin-bottom: 16px;
	}

	.toolbar-btn {
		flex: 1;
		background: rgba(0, 0, 0, 0.04);
		border: none;
		padding: 8px 10px;
		border-radius: 8px;
		font-size: 11px;
		font-weight: 500;
		color: #666;
		cursor: pointer;
		transition: all 0.2s;
	}

	.toolbar-btn:hover {
		background: rgba(0, 0, 0, 0.08);
		color: #333;
	}

	.apply-btn {
		background: rgba(0, 0, 235, 0.1);
		color: #0000eb;
	}

	.apply-btn:hover {
		background: rgba(0, 0, 235, 0.2);
		color: #0000cc;
	}

	.save-form {
		background: rgba(255, 255, 255, 0.6);
		border: 1px solid rgba(0, 0, 0, 0.08);
		border-radius: 10px;
		padding: 12px;
		margin-bottom: 16px;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	
	.save-btn {
		background: rgba(26, 26, 26, 0.9);
		color: white;
		border: none;
		padding: 8px;
		border-radius: 6px;
		font-size: 12px;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.2s;
	}

	.save-btn:hover {
		background: rgba(0, 0, 0, 1);
	}

	.params-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 48px 24px;
		color: #999;
		font-size: 13px;
		text-align: center;
		gap: 12px;
	}
	.params-empty-icon { font-size: 32px; opacity: 0.5; }

	.obj-block {
		background: var(--bg-primary);
		border: 1px solid var(--border-secondary);
		border-radius: var(--radius-2xl);
		margin-bottom: var(--spacing-lg);
		overflow: hidden;
	}
	.obj-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--spacing-xl) var(--spacing-xl);
		cursor: pointer;
		user-select: none;
		list-style: none;
		font-size: var(--font-lg);
		font-weight: 600;
		color: var(--text-primary);
	}
	.obj-header::-webkit-details-marker { display: none; }
	.obj-name { flex: 1; }
	.obj-badge {
		background: var(--primary-blue-light);
		color: var(--primary-blue);
		font-size: var(--font-sm);
		font-weight: 500;
		padding: var(--spacing-xs) var(--spacing-md);
		border-radius: var(--radius-xl);
	}

	.section-block {
		margin: 0 var(--spacing-xl) var(--spacing-md);
		border: 1px solid var(--border-secondary);
		border-radius: var(--radius-md);
		background: var(--bg-primary);
		overflow: hidden;
	}
	.section-header {
		display: flex;
		align-items: center;
		gap: var(--spacing-md);
		padding: var(--spacing-md) var(--spacing-lg);
		cursor: pointer;
		user-select: none;
		list-style: none;
		font-size: var(--font-lg);
		font-weight: 600;
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 0.4px;
	}
	.section-header::-webkit-details-marker { display: none; }
	.count-badge {
		background: var(--bg-subtle-light);
		color: var(--text-light);
		font-size: var(--font-sm);
		font-weight: 400;
		padding: 1px var(--spacing-sm);
		border-radius: var(--radius-md);
		text-transform: none;
		letter-spacing: 0;
	}

	.vars-grid {
		padding: 2px 10px 8px;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.var-row {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		font-size: 12px;
		min-height: 28px;
	}
	.var-label-section {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 110px;
		flex-shrink: 0;
	}
	.var-key {
		color: #555;
		font-weight: 500;
	}
	.var-desc {
		color: #888;
		font-size: 9px;
		line-height: 1.3;
		font-style: italic;
		white-space: normal;
		word-wrap: break-word;
	}
	.var-val {
		color: #0000eb;
		font-family: monospace;
		font-size: 11px;
	}

	.actions-list {
		padding: 2px 10px 8px;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.action-block {
		border: 1px solid rgba(0,0,0,0.05);
		border-radius: 6px;
		background: rgba(255,255,255,0.4);
		overflow: hidden;
	}
	.action-summary {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 5px 8px;
		cursor: pointer;
		user-select: none;
		list-style: none;
		font-size: 11px;
	}
	.action-summary::-webkit-details-marker { display: none; }
	.action-num {
		color: #bbb;
		font-size: 10px;
		min-width: 14px;
	}
	.action-op {
		color: #1a1a1a;
		font-weight: 600;
		flex: 1;
	}
	.action-as {
		color: #888;
		font-size: 10px;
	}
	.action-view-toggle {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		padding: 0;
		border: none;
		background: transparent;
		cursor: pointer;
		opacity: 0.4;
		transition: opacity 0.2s;
		flex-shrink: 0;
	}
	.action-view-toggle:hover {
		opacity: 0.8;
	}
	.action-view-toggle.visible {
		opacity: 0.7;
	}
	.action-view-toggle.visible:hover {
		opacity: 1;
	}
	.action-view-toggle svg {
		width: 14px;
		height: 14px;
		stroke: #666;
	}
	.action-view-toggle.visible svg {
		stroke: var(--primary-blue);
	}
	.action-body {
		padding: 0;
		display: flex;
		flex-direction: column;
	}
	.param-form {
		padding: 4px 8px 8px;
		display: flex;
		flex-direction: column;
		gap: 3px;
		border-top: 1px solid rgba(0,0,0,0.05);
		background: rgba(0,0,0,0.02);
	}
	.param-row {
		display: grid;
		grid-template-columns: auto 1fr;
		align-items: center;
		gap: 8px;
		min-height: 22px;
	}
	.param-label {
		color: #666;
		font-size: 10px;
		font-weight: 500;
		text-align: left;
		white-space: nowrap;
	}
	.pi {
		flex: 1;
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		background: var(--bg-input);
		color: var(--text-secondary);
		font-size: var(--font-lg);
		padding: var(--spacing-sm) var(--spacing-md);
		outline: none;
		min-width: 0;
		max-width: 140px;
		text-align: left;
	}
	.pi-num { font-family: monospace; }
	.pi-str { color: var(--primary-blue); font-family: monospace; }
	.pi-color { width: 28px; height: 20px; padding: 1px 2px; cursor: pointer; flex: none; }
	.pi-color-wrap { display: flex; align-items: center; gap: var(--spacing-sm); }
	.pi-color-label { font-size: var(--font-lg); color: var(--text-dim); font-family: monospace; }
	.pi-check { width: 14px; height: 14px; cursor: pointer; flex: none; }
	.pi-complex { flex: 1; }
	.pi-complex-toggle {
		cursor: pointer;
		font-size: var(--font-base);
		color: var(--text-light);
		list-style: none;
		padding: var(--spacing-sm) var(--spacing-md);
		background: var(--bg-subtle);
		border-radius: var(--radius-sm);
		display: inline-block;
	}
	.pi-complex-toggle::-webkit-details-marker { display: none; }
	.pi-json {
		margin: var(--spacing-md) 0 0;
		padding: var(--spacing-md) var(--spacing-lg);
		font-size: var(--font-base);
		font-family: monospace;
		color: var(--text-dim);
		white-space: pre-wrap;
		word-break: break-all;
		max-height: 150px;
		overflow-y: auto;
		background: var(--bg-primary);
		border: 1px solid var(--border-secondary);
		border-radius: var(--radius-sm);
	}
	.pi-arr-objs { flex: 1; display: flex; flex-direction: column; gap: 2px; }
	.pi-arr-item { border: 1px solid rgba(0,0,0,0.06); border-radius: 4px; background: rgba(255,255,255,0.5); overflow: hidden; }
	.pi-arr-toggle { cursor: pointer; font-size: 10px; color: #666; list-style: none; padding: 2px 6px; display: block; font-family: monospace; }
	.pi-arr-toggle::-webkit-details-marker { display: none; }
	.pi-arr-body { padding: 2px 6px 4px; border-top: 1px solid rgba(0,0,0,0.05); }
	.pi-sub-obj { flex: 1; display: flex; flex-direction: column; gap: 2px; }
	.pi-sub-row { padding-left: 4px; }
	.pi-sub-label { color: #999; font-size: 10px; min-width: 80px; }
	
	/* Nested actions styles */
	.pi-nested-actions-wrapper {
		display: flex;
		flex-direction: column;
		gap: var(--spacing-lg);
		margin: var(--spacing-lg) 0;
		width: 100%;
	}
	.pi-nested-header {
		font-size: var(--font-sm);
		font-weight: 600;
		color: var(--text-light);
		background: rgba(0,0,0,0.04);
		padding: 6px 10px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		user-select: none;
		letter-spacing: 0.02em;
		list-style: none;
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.pi-nested-actions { 
		display: flex; 
		flex-direction: column; 
		gap: var(--spacing-md); 
		/* padding-left: var(--spacing-md); */
	}
	.pi-nested-action { 
		border-radius: var(--radius-sm); 
		background: var(--bg-primary);
		overflow: hidden;
		border: 1px solid rgba(0,0,0,0.08);
		margin-bottom: 4px;
	}
	.pi-nested-toggle { 
		cursor: pointer; 
		font-size: var(--font-sm); 
		font-weight: 600;
		color: var(--text-light);
		background: rgba(0,0,0,0.04);
		padding: 6px 10px;
		user-select: none;
		letter-spacing: 0.02em;
		list-style: none;
		display: flex;
		align-items: center;
		gap: 6px;
		border-bottom: 1px solid rgba(0,0,0,0.08);
	}
	.pi-nested-toggle::-webkit-details-marker { display: none; }
	.pi-nested-num { 
		background: var(--text-light);
		color: white; 
		border-radius: var(--radius-sm); 
		padding: 1px var(--spacing-sm); 
		font-size: var(--font-sm); 
		font-weight: bold; 
		min-width: 16px; 
		text-align: center;
	}
	.pi-nested-op { 
		font-weight: 600; 
		color: var(--text-light);
		flex: 1;
	}
	.pi-nested-name { 
		color: var(--text-light);
		font-size: var(--font-sm);
		font-style: italic;
	}
	.pi-nested-body { 
		padding: 4px 6px;
		border-top: none;
		background: var(--bg-primary);
	}
	.pi-nested-controls { 
		display: flex; 
		gap: 4px; 
		margin-top: 6px; 
		padding-top: 6px; 
		border-top: 1px solid rgba(0, 0, 235, 0.1);
	}
	.pi-add-nested-btn { 
		font-size: 10px; 
		padding: 4px 8px; 
		background: #0000eb; 
		color: white; 
		border: none; 
		border-radius: 3px; 
		cursor: pointer;
		flex: 1;
	}
	.pi-add-nested-btn:hover { 
		background: #0000d0; 
	}
	.pi-remove-nested-btn { 
		font-size: 9px; 
		padding: 2px 6px; 
		background: #b00020; 
		color: white; 
		border: none; 
		border-radius: 3px; 
		cursor: pointer;
	}
	.pi-remove-nested-btn:hover { 
		background: #a00018; 
	}
	.pi-nested-obj {
		margin: 4px 0;
		border: 1px solid rgba(0, 0, 0, 0.1);
		border-radius: 4px;
		background: rgba(0, 0, 0, 0.02);
	}
	.pi-nested-obj-toggle {
		cursor: pointer;
		font-size: 10px;
		font-weight: 600;
		color: #0000eb;
		list-style: none;
		padding: 4px 8px;
		background: rgba(0, 0, 235, 0.05);
		border-bottom: 1px solid rgba(0, 0, 235, 0.1);
	}
	.pi-nested-obj-toggle::-webkit-details-marker { display: none; }
	.pi-nested-obj-body {
		padding: 4px 6px;
	}
	.pi-deep-row {
		padding-left: 8px;
		border-left: 2px solid rgba(0, 0, 0, 0.06);
		margin-left: 4px;
	}
	.pi-deep-label {
		font-size: 9px;
		color: #777;
		min-width: 100px;
	}
	.pi-deeper-obj {
		margin: 4px 0 4px 8px;
		border: 1px solid rgba(0, 0, 0, 0.08);
		border-radius: 3px;
		background: rgba(0, 0, 0, 0.01);
	}
	.pi-deeper-obj-toggle {
		cursor: pointer;
		font-size: 9px;
		font-weight: 600;
		color: #666;
		list-style: none;
		padding: 3px 6px;
		background: rgba(0, 0, 0, 0.02);
		border-bottom: 1px solid rgba(0, 0, 0, 0.06);
	}
	.pi-deeper-obj-toggle::-webkit-details-marker { display: none; }
	.pi-deeper-obj-body {
		padding: 3px 4px;
	}
	.pi-deeper-row {
		padding-left: 12px;
		border-left: 2px solid rgba(0, 0, 0, 0.04);
		margin-left: 6px;
	}
	.pi-deeper-label {
		font-size: 8px;
		color: #888;
		min-width: 90px;
	}
	.pi-expr {
		flex: 1;
		padding: var(--spacing-md) var(--spacing-lg);
		border: 1px solid #ddd;
		border-radius: var(--radius-sm);
		font-size: var(--font-base);
		font-family: 'Courier New', monospace;
		background: #fffef5;
		color: var(--text-muted);
	}
	.pi-expr:focus {
		outline: none;
		border-color: var(--border-focus);
		background: #fff;
	}
	.params-actions {
		display: flex;
		gap: 8px;
		padding: 10px 8px 4px;
		border-top: 1px solid rgba(0,0,0,0.08);
		margin-top: 8px;
	}
	.params-apply-btn {
		flex: 1;
		padding: 7px 0;
		background: #0000eb;
		color: #fff;
		border: none;
		border-radius: 6px;
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		transition: background 0.15s;
	}
	.params-apply-btn:hover { background: #0000c9; }
	.params-reset-btn {
		padding: 7px 14px;
		background: rgba(0,0,0,0.06);
		color: #555;
		border: 1px solid rgba(0,0,0,0.10);
		border-radius: 6px;
		font-size: 12px;
		cursor: pointer;
		transition: background 0.15s;
	}
	.params-reset-btn:hover { background: rgba(0,0,0,0.10); }

	.controls-container {
		min-height: 200px;
		font-family: inherit;
		font-size: 12px;
		max-height: calc(100vh - 280px);
		overflow-y: auto;
		padding-right: 4px;
	}

	/* ParameterEditor content styles */
	:global(.controls-container .parameter-group) {
		margin-bottom: 8px;
		border: 1px solid #e0e0e0;
		border-radius: 6px;
		padding: 6px 8px;
		background: #f8f9fa;
	}
	:global(.controls-container h4) {
		margin: 0 0 6px 0;
		font-size: 11px;
		font-weight: 600;
		color: #667eea;
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}
	:global(.controls-container .parameter-control) {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 4px;
		font-size: 11px;
	}
	:global(.controls-container .parameter-control label) {
		color: #555;
		min-width: 90px;
		flex-shrink: 0;
		font-size: 11px;
		font-weight: 500;
	}
	:global(.controls-container .parameter-control input[type="number"],
	        .controls-container .parameter-control input[type="text"],
	        .controls-container .parameter-control select) {
		flex: 1;
		background: #fff;
		border: 1px solid #d0d0d0;
		color: #333;
		padding: 2px 6px;
		border-radius: 3px;
		font-size: 11px;
		min-width: 0;
	}
	:global(.controls-container .parameter-control input[type="color"]) {
		width: 32px;
		height: 22px;
		padding: 1px;
		border: 1px solid #d0d0d0;
		border-radius: 3px;
		background: #fff;
		cursor: pointer;
	}
	:global(.controls-container .json-editor) {
		width: 100%;
		min-height: 50px;
		background: #fff;
		border: 1px solid #d0d0d0;
		color: #333;
		font-size: 10px;
		font-family: monospace;
		padding: 4px;
		border-radius: 3px;
		resize: vertical;
	}
	:global(.controls-container details) {
		font-size: 11px;
	}
	:global(.controls-container details summary) {
		cursor: pointer;
		color: #0000eb;
		padding: 2px 0;
		user-select: none;
		font-weight: 500;
	}
	:global(.controls-container .effect-howto) {
		background: #0000eb10;
		border: 1px solid #d0d8f0;
		border-radius: 4px;
		margin-bottom: 6px;
		padding: 4px 8px;
	}
	:global(.controls-container .howto-body) {
		padding: 4px 0;
		color: #666;
		font-size: 10px;
		line-height: 1.4;
	}
	:global(.controls-container .howto-desc) { margin-bottom: 4px; }
	:global(.controls-container .howto-param strong) { color: #0000eb; }
	
	/* How it works styling for action panels */
	.effect-howto summary {
		cursor: pointer;
		color: #0000eb;
		background-color: #0000eb10;
		padding: 4px;
		user-select: none;
		font-weight: 500;
		font-size: 11px;
	}
	.effect-howto summary::-webkit-details-marker { display: none; }
	.howto-body {
		padding: 4px;
		color: #666;
		background-color: #0000eb10;
		font-size: 10px;
		line-height: 1.4;
	}
	.howto-desc {
		margin-bottom: 4px;
		color: #333;
		font-size: 10px;
		line-height: 1.4;
	}
	.howto-desc strong {
		color: #0000eb;
		font-weight: 600;
	}
	.howto-param {
		margin-bottom: 2px;
		color: #555;
		font-size: 9px;
		line-height: 1.3;
	}
	.howto-param strong {
		color: #0000eb;
		font-weight: 600;
	}
	.pi-param-default {
		color: #888;
		font-size: 8px;
		font-style: italic;
		margin-left: 4px;
	}
	:global(.controls-container::-webkit-scrollbar) {
		width: 6px;
	}
	:global(.controls-container::-webkit-scrollbar-track) {
		background: #f1f1f1;
		border-radius: 3px;
	}
	:global(.controls-container::-webkit-scrollbar-thumb) {
		background: #c1c1c1;
		border-radius: 3px;
	}
	:global(.controls-container::-webkit-scrollbar-thumb:hover) {
		background: #a8a8a8;
	}

	/* Floating Toggle Button */
	.floating-toggle {
		position: fixed;
		top: var(--spacing-3xl);
		left: var(--spacing-3xl);
		width: 44px;
		height: 44px;
		background: var(--bg-panel);
		backdrop-filter: blur(30px);
		-webkit-backdrop-filter: blur(20px);
		border: 1px solid rgba(255, 255, 255, 0.4);
		border-radius: var(--radius-xl);
		box-shadow: var(--shadow-panel);
		cursor: pointer;
		z-index: 200;
		display: flex;
		align-items: center;
		justify-content: center;
		transition: all 0.2s;
		color: var(--text-dim);
	}

	.floating-toggle:hover {
		background: var(--bg-hover);
		transform: translateY(-2px);
		box-shadow: var(--shadow-panel);
	}

	.floating-toggle svg {
		width: 20px;
		height: 20px;
	}

	/* Chat Tab Styles */
	.chat-tab {
		display: flex;
		flex-direction: column;
		height: 100%;
		flex: 1;
		min-height: 0;
	}

	.chat-messages {
		flex: 1;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding-bottom: 12px;
		min-height: 0;
	}

	.chat-messages::-webkit-scrollbar {
		width: 6px;
	}

	.chat-messages::-webkit-scrollbar-track {
		background: transparent;
	}

	.chat-messages::-webkit-scrollbar-thumb {
		background: rgba(0, 0, 0, 0.15);
		border-radius: 3px;
	}

	.chat-welcome {
		background: rgba(255, 255, 255, 0.6);
		border: 1px solid rgba(0, 0, 0, 0.06);
		border-radius: 12px;
		padding: 16px;
		text-align: center;
		margin: auto 0;
	}

	.welcome-title {
		font-size: 16px;
		font-weight: 600;
		color: #1a1a1a;
		margin-bottom: 8px;
	}

	.welcome-text {
		font-size: 13px;
		color: #666;
		line-height: 1.5;
		margin-bottom: 12px;
	}

	.welcome-examples {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.example-chip {
		background: rgba(0, 0, 235, 0.08);
		border: 1px solid rgba(0, 0, 235, 0.15);
		border-radius: 8px;
		padding: 8px 12px;
		font-size: 12px;
		color: #0000eb;
		cursor: pointer;
		transition: all 0.2s;
	}

	.example-chip:hover {
		background: rgba(0, 0, 235, 0.15);
		border-color: rgba(0, 0, 235, 0.25);
	}

	/* Message wrapper for alignment */
	.chat-message-wrapper {
		display: flex;
		width: 100%;
	}

	.chat-message-wrapper.user {
		justify-content: flex-end;
	}

	.chat-message-wrapper.assistant {
		justify-content: flex-start;
	}

	.chat-message {
		max-width: 85%;
		background: rgba(255, 255, 255, 0.9);
		border: 1px solid rgba(0, 0, 0, 0.06);
		border-radius: 16px;
		padding: 10px 14px;
	}

	.chat-message.user {
		background: rgba(0, 0, 235, 0.12);
		border-color: rgba(0, 0, 235, 0.2);
		border-bottom-right-radius: 4px;
	}

	.chat-message.assistant {
		background: rgba(255, 255, 255, 0.95);
		border-bottom-left-radius: 4px;
	}

	.chat-message.error {
		background: rgba(235, 0, 0, 0.08);
		border-color: rgba(235, 0, 0, 0.15);
	}

	.chat-message.generating {
		opacity: 0.8;
	}

	.message-header {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 4px;
		font-size: 11px;
	}

	.message-header .role {
		font-weight: 600;
		color: #666;
	}

	.message-header .typing {
		color: #888;
		font-style: italic;
	}

	.message-content {
		font-size: 13px;
		color: #333;
		line-height: 1.5;
		white-space: pre-wrap;
	}

	.stage-indicator {
		font-size: 11px;
		color: #0000eb;
		margin-top: 6px;
	}

	.chat-input-area {
		display: flex;
		align-items: center;
		gap: 8px;
		background: rgba(255, 255, 255, 0.9);
		border: 1px solid rgba(0, 0, 0, 0.08);
		border-radius: 12px;
		padding: 8px 10px;
		margin-top: 8px;
		flex-shrink: 0;
	}

	.chat-input-area textarea {
		flex: 1;
		background: transparent;
		border: none;
		resize: none;
		font-size: 13px;
		color: #1a1a1a;
		outline: none;
		min-height: 24px;
		max-height: 100px;
		line-height: 1.4;
		font-family: inherit;
	}

	.chat-input-area textarea::placeholder {
		color: #aaa;
	}

	.chat-input-area textarea:disabled {
		opacity: 0.6;
	}

	.chat-input-area .send-btn {
		width: 32px;
		height: 32px;
		min-width: 32px;
		border-radius: 50%;
		background: #0000eb;
		border: none;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		transition: background 0.15s;
	}

	.chat-input-area .send-btn:hover:not(:disabled) {
		background: #0000c0;
	}

	.chat-input-area .send-btn:disabled {
		background: #ccc;
		cursor: not-allowed;
	}

	.chat-input-area .send-btn svg {
		width: 14px;
		height: 14px;
		fill: #fff;
	}

	.chat-input-area .new-chat-btn {
		width: 32px;
		height: 32px;
		min-width: 32px;
		border-radius: 50%;
		background: transparent;
		border: none;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		transition: all 0.15s;
		color: #0000eb;
		flex-shrink: 0;
	}

	.chat-input-area .new-chat-btn:hover {
		color: #0000c0;
		transform: scale(1.1);
	}

	.chat-input-area .new-chat-btn svg {
		width: 18px;
		height: 18px;
	}

	.edit-btn {
		background: transparent;
		border: none;
		cursor: pointer;
		padding: 2px;
		opacity: 0;
		transition: opacity 0.15s;
		color: #666;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.chat-message:hover .edit-btn {
		opacity: 0.6;
	}

	.edit-btn:hover {
		opacity: 1 !important;
		color: #0000eb;
	}

	.edit-btn svg {
		width: 12px;
		height: 12px;
	}

	.chat-input-area .clear-btn {
		background: transparent;
		border: none;
		cursor: pointer;
		font-size: 14px;
		padding: 4px;
		opacity: 0.6;
		transition: opacity 0.15s;
		flex-shrink: 0;
	}

	.chat-input-area .clear-btn:hover {
		opacity: 1;
	}

	.chat-loading {
		width: 32px;
		height: 32px;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.chat-loading .spinner {
		width: 18px;
		height: 18px;
		border: 2px solid #ddd;
		border-top-color: #0000eb;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	/* Scene Tab Styles */
	.scene-controls {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.scene-section {
		background: rgba(255,255,255,0.6);
		border: 1px solid rgba(0,0,0,0.08);
		border-radius: 10px;
		overflow: hidden;
	}

	.scene-section .section-header {
		padding: 10px 14px;
		font-size: 12px;
		font-weight: 600;
		color: #1a1a1a;
		background: rgba(0,0,0,0.02);
		text-transform: none;
		letter-spacing: normal;
	}

	.scene-control-row {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 8px 14px;
		border-top: 1px solid rgba(0,0,0,0.05);
	}

	.scene-label {
		color: #555;
		font-size: 12px;
		font-weight: 500;
		min-width: 100px;
		flex-shrink: 0;
	}

	.scene-color-wrap {
		display: flex;
		align-items: center;
		gap: 8px;
		flex: 1;
	}

	.scene-color {
		width: 32px;
		height: 24px;
		padding: 1px;
		border: 1px solid rgba(0,0,0,0.15);
		border-radius: 4px;
		background: #fff;
		cursor: pointer;
		flex-shrink: 0;
	}

	.scene-color-label {
		font-size: 12px;
		color: #666;
		font-family: monospace;
	}

	.scene-slider {
		flex: 1;
		height: 4px;
		background: rgba(0,0,0,0.1);
		border-radius: 2px;
		outline: none;
		cursor: pointer;
	}

	.scene-slider::-webkit-slider-thumb {
		width: 14px;
		height: 14px;
		background: #0000eb;
		border-radius: 50%;
		cursor: pointer;
		-webkit-appearance: none;
	}

	.scene-slider::-moz-range-thumb {
		width: 14px;
		height: 14px;
		background: #0000eb;
		border-radius: 50%;
		cursor: pointer;
		border: none;
	}

	.scene-value {
		font-size: 12px;
		color: #666;
		font-family: monospace;
		min-width: 24px;
		text-align: right;
	}

	.toggle-switch {
		position: relative;
		display: inline-block;
		width: 36px;
		height: 20px;
	}

	.toggle-switch input {
		opacity: 0;
		width: 0;
		height: 0;
	}

	.toggle-slider {
		position: absolute;
		cursor: pointer;
		top: 0;
		left: 0;
		right: 0;
		bottom: 0;
		background-color: #ccc;
		border-radius: 20px;
		transition: 0.2s;
	}

	.toggle-slider:before {
		position: absolute;
		content: "";
		height: 14px;
		width: 14px;
		left: 3px;
		bottom: 3px;
		background-color: white;
		border-radius: 50%;
		transition: 0.2s;
	}

	.toggle-switch input:checked + .toggle-slider {
		background-color: #0000eb;
	}

	.toggle-switch input:checked + .toggle-slider:before {
		transform: translateX(16px);
	}

	.scene-btn {
		flex: 1;
		padding: 8px 12px;
		background: rgba(0,0,0,0.06);
		border: 1px solid rgba(0,0,0,0.10);
		border-radius: 6px;
		font-size: 12px;
		color: #333;
		cursor: pointer;
		transition: all 0.15s;
	}

	.scene-btn:hover {
		background: rgba(0,0,235,0.1);
		border-color: rgba(0,0,235,0.2);
		color: #0000eb;
	}

	/* Render Tab Styles */
	.render-tab {
		height: 100%;
		overflow-y: auto;
	}

	.render-tab::-webkit-scrollbar {
		width: 6px;
	}

	.render-tab::-webkit-scrollbar-track {
		background: transparent;
	}

	.render-tab::-webkit-scrollbar-thumb {
		background: rgba(0, 0, 0, 0.15);
		border-radius: 3px;
	}

	/* Expression display styles */
	.param-expr {
		font-size: 10px;
		color: var(--text-muted);
		font-family: monospace;
		margin-top: var(--spacing-sm);
		padding: var(--spacing-sm) var(--spacing-md);
		background: #f5f5f5;
		border-radius: var(--radius-sm);
		word-break: break-all;
	}

	.pi-complex {
		font-family: monospace;
		font-size: var(--font-base);
		background: #f8f9fa;
		border: 1px solid #e0e0e0;
		color: var(--text-secondary);
		resize: vertical;
		min-height: 60px;
	}

	.param-row-full {
		grid-column: 1 / -1;
	}

	.pi-object-group {
		grid-column: 1 / -1;
	}

	.pi-object-details {
		border-left: 2px solid #0000eb;
		padding-left: 8px;
		width: 100%;
	}

	.pi-object-label {
		font-size: 10px;
		font-weight: 600;
		color: #0000eb;
		text-transform: uppercase;
		letter-spacing: 0.3px;
		margin-bottom: 4px;
		text-align: left;
		cursor: pointer;
		user-select: none;
		list-style: none;
		padding: 2px 0;
	}

	.pi-object-label::-webkit-details-marker {
		display: none;
	}

	.pi-object-content {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-top: 4px;
	}

	.pi-deeper {
		margin-left: 0;
		padding-left: 12px;
		border-left: 2px solid #d0d0d0;
	}

	.guidance-section {
		margin-bottom: 16px;
	}

	.guidance-section:last-child {
		margin-bottom: 0;
	}

	.guidance-section h4 {
		margin: 0 0 6px 0;
		font-size: 12px;
		font-weight: 600;
		color: #333;
	}

	.guidance-section p {
		margin: 0 0 8px 0;
		font-size: 11px;
		line-height: 1.4;
		color: #666;
	}

	.guidance-examples {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.example-good, .example-bad {
		padding: 6px 10px;
		border-radius: 6px;
		font-size: 10px;
		line-height: 1.3;
		border: 1px solid;
	}

	.example-good {
		background: rgba(0, 0, 0, 0.03);
		border-color: rgba(0, 0, 0, 0.1);
		color: #333;
	}

	.example-bad {
		background: rgba(0, 0, 0, 0.06);
		border-color: rgba(0, 0, 0, 0.15);
		color: #666;
	}

	.guidance-tips {
		margin-top: 16px;
		padding-top: 12px;
		border-top: 1px solid rgba(0,0,0,0.06);
	}

	.guidance-tips h4 {
		margin: 0 0 8px 0;
		font-size: 12px;
		font-weight: 600;
		color: #333;
	}

	.guidance-tips ul {
		margin: 0;
		padding-left: 16px;
	}

	.guidance-tips li {
		margin-bottom: 4px;
		font-size: 11px;
		line-height: 1.4;
		color: #666;
	}

	.guidance-tips li:last-child {
		margin-bottom: 0;
	}

	.sg-group {
		border: 1px solid rgba(0,0,0,0.08);
		border-radius: var(--radius-sm);
		margin-bottom: 4px;
		overflow: hidden;
		background: var(--bg-primary);
	}

	.sg-group-summary {
		padding: var(--spacing-md) var(--spacing-lg);
		font-size: var(--font-base);
		color: var(--primary-blue);
		background: var(--primary-blue-light);
		border-bottom: 1px solid rgba(0, 0, 235, 0.1);
		cursor: pointer;
		user-select: none;
		list-style: none;
		display: flex;
		align-items: center;
		gap: var(--spacing-md);
		font-weight: 600;
	}

	.sg-group-summary::-webkit-details-marker { display: none; }

	.sg-group-body {
		padding: var(--spacing-md) var(--spacing-lg);
		border-top: none;
		background: var(--bg-primary);
	}

	.sg-deep-group {
		margin: 2px 0;
		border-left: 2px solid rgba(0,0,0,0.1);
		padding-left: 6px;
	}

	.sg-deep-label {
		font-size: var(--font-sm);
		font-weight: 600;
		color: var(--text-dim);
		cursor: pointer;
		list-style: none;
		padding: 3px 0;
	}

	.sg-deep-label::-webkit-details-marker { display: none; }

	.sg-deep-body {
		padding-left: 4px;
	}

	/* Make params-grid match sg-group styling */
	.params-grid {
		border: 1px solid rgba(0,0,0,0.08);
		border-radius: var(--radius-sm);
		margin-bottom: 4px;
		overflow: hidden;
		background: var(--bg-primary);
	}

	.param-row-json {
		align-items: flex-start;
	}

	.pi-json-input {
		flex: 1;
		width: 100%;
		font-family: monospace;
		font-size: var(--font-sm);
		background: var(--bg-input, rgba(0,0,0,0.05));
		border: 1px solid rgba(0,0,0,0.12);
		border-radius: var(--radius-sm);
		padding: 4px 6px;
		resize: vertical;
		color: var(--text-main);
		line-height: 1.4;
	}

	.pi-val-text {
		font-size: var(--font-sm);
		color: var(--text-dim);
		font-family: monospace;
		word-break: break-all;
	}

	.pi-sub-row {
		padding-left: 8px;
	}

	.pi-sub-label {
		font-size: var(--font-sm);
		color: var(--text-dim);
	}
</style>
