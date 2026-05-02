<script lang="ts">
	type ChatMsg = { role: 'user' | 'assistant'; content: string; imageDataUrl?: string };

	const MODEL_OPTIONS = [
		{ value: 'gpt-5.5', label: 'GPT-5.5' },
		{ value: 'gpt-5.4', label: 'GPT-5.4' },
		{ value: 'gpt-4o', label: 'GPT-4o' }
	] as const;

	const PROCEDURAL_EXAMPLES = [
		{ text: 'Create a box at position [0,0,0] with size [1,1,1]', category: 'Primitives' },
		{ text: 'Create a sphere with radius 0.5 at origin', category: 'Primitives' },
		{ text: 'Extrude a rectangular profile to create a wall', category: 'Profile' },
		{ text: 'Revolve a profile around the z-axis to create a vase', category: 'Profile' },
		{ text: 'Subtract a cylinder from a box to create a hole', category: 'Boolean' },
		{ text: 'Union two spheres to create a merged shape', category: 'Boolean' },
		{ text: 'Scale the object by factor 2.0', category: 'Transform' },
		{ text: 'Rotate the object 45 degrees around the z-axis', category: 'Transform' },
		{ text: 'Apply a taper deformation along the z-axis', category: 'Deformation' },
		{ text: 'Add a bevel with 0.05 distance to all edges', category: 'Modifiers' },
		{ text: 'Generate a cellular automata coral structure', category: 'Simulation' },
		{ text: 'Create a differential growth pattern', category: 'Simulation' }
	];

	const LLM_ONLY_EXAMPLES = [
		{ text: 'Create a simple cube with 8 vertices and 12 triangular faces', category: 'Basic Shapes' },
		{ text: 'Create a pyramid with a square base and triangular sides', category: 'Basic Shapes' },
		{ text: 'Create a low-poly sphere with approximately 100 vertices', category: 'Basic Shapes' },
		{ text: 'Create a torus (donut shape) with tube radius 0.2 and ring radius 1.0', category: 'Basic Shapes' },
		{ text: 'Create a simple chair with seat, back, and 4 legs', category: 'Objects' },
		{ text: 'Create a table with a rectangular top and 4 cylindrical legs', category: 'Objects' },
		{ text: 'Create a simple lamp with a base, stem, and shade', category: 'Objects' },
		{ text: 'Create a low-poly tree trunk and foliage', category: 'Organic' },
		{ text: 'Create a simple flower with petals and stem', category: 'Organic' },
		{ text: 'Create a simple house with walls, roof, and door', category: 'Architecture' },
		{ text: 'Create a simple car body with wheels', category: 'Objects' },
		{ text: 'Create a rock formation with irregular geometry', category: 'Organic' }
	];

	const OBJ_EXAMPLES = [
		{
			name: 'Arched Wall Opening',
			liveObj: `#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@kernel_default: cadquery

o wall_arch_profile_hole
#@source: procedural
#@type: extrude
#@params: kernel=cadquery, profile=[[0,0,0],[4.0,0,0],[4.0,0,3.0],[0,0,3.0],[0,0,0],None,[1.0,0,0],[3.0,0,0],[3.0,0,1.8],[2.97,0,2.0],[2.88,0,2.2],[2.75,0,2.37],[2.57,0,2.55],[2.4,0,2.68],[2.2,0,2.77],[2.0,0,2.8],[1.8,0,2.77],[1.6,0,2.68],[1.43,0,2.55],[1.25,0,2.37],[1.12,0,2.2],[1.03,0,2.0],[1.0,0,1.8],[1.0,0,0]], height=0.25, segments=32`
		},
		{
			name: 'Fluid Organic Vase',
			liveObj: `#@kernel_default: cadquery
o fluid_organic_vase
v 0.390000 0.000000 0.000000
v 0.291000 0.212000 0.000000
v 0.124000 0.380000 0.000000
v -0.114000 0.352000 0.000000
v -0.332000 0.241000 0.000000
v -0.380000 0.000000 0.000000
v -0.283000 -0.206000 0.000000
v -0.124000 -0.380000 0.000000
v 0.111000 -0.342000 0.000000
v 0.316000 -0.229000 0.000000
v 0.580000 -0.010000 0.180000
v 0.449000 0.302000 0.180000
v 0.199000 0.542000 0.180000
v -0.141000 0.485000 0.180000
v -0.441000 0.325000 0.180000
v -0.530000 -0.010000 0.180000
v -0.385000 -0.304000 0.180000
v -0.147000 -0.524000 0.180000
v 0.181000 -0.505000 0.180000
v 0.473000 -0.339000 0.180000
v 0.850000 0.020000 0.550000
v 0.657000 0.461000 0.550000
v 0.303000 0.800000 0.550000
v -0.185000 0.743000 0.550000
v -0.589000 0.485000 0.550000
v -0.690000 0.020000 0.550000
v -0.573000 -0.433000 0.550000
v -0.200000 -0.750000 0.550000
v 0.291000 -0.722000 0.550000
v 0.721000 -0.468000 0.550000
v 0.480000 0.040000 0.950000
v 0.352000 0.310000 0.950000
v 0.138000 0.525000 0.950000
v -0.165000 0.487000 0.950000
v -0.416000 0.328000 0.950000
v -0.470000 0.040000 0.950000
v -0.425000 -0.254000 0.950000
v -0.184000 -0.464000 0.950000
v 0.128000 -0.416000 0.950000
v 0.401000 -0.266000 0.950000
v 0.570000 0.000000 1.350000
v 0.425000 0.353000 1.350000
v 0.144000 0.628000 1.350000
v -0.242000 0.561000 1.350000
v -0.586000 0.382000 1.350000
v -0.670000 0.000000 1.350000
v -0.529000 -0.341000 1.350000
v -0.258000 -0.609000 1.350000
v 0.132000 -0.590000 1.350000
v 0.482000 -0.394000 1.350000
v 0.720000 -0.040000 1.750000
v 0.550000 0.360000 1.750000
v 0.226000 0.654000 1.750000
v -0.207000 0.597000 1.750000
v -0.574000 0.377000 1.750000
v -0.690000 -0.040000 1.750000
v -0.534000 -0.428000 1.750000
v -0.222000 -0.725000 1.750000
v 0.216000 -0.706000 1.750000
v 0.599000 -0.475000 1.750000
v 0.410000 -0.020000 2.050000
v 0.315000 0.180000 2.050000
v 0.157000 0.341000 2.050000
v -0.068000 0.313000 2.050000
v -0.251000 0.192000 2.050000
v -0.290000 -0.020000 2.050000
v -0.235000 -0.220000 2.050000
v -0.074000 -0.372000 2.050000
v 0.148000 -0.353000 2.050000
v 0.356000 -0.249000 2.050000
v 0.450000 0.010000 2.280000
v 0.344000 0.245000 2.280000
v 0.159000 0.438000 2.280000
v -0.107000 0.400000 2.280000
v -0.336000 0.269000 2.280000
v -0.370000 0.010000 2.280000
v -0.304000 -0.225000 2.280000
v -0.113000 -0.399000 2.280000
v 0.147000 -0.380000 2.280000
v 0.384000 -0.255000 2.280000
v 0.510000 0.020000 2.420000
v 0.380000 0.296000 2.420000
v 0.161000 0.515000 2.420000
v -0.148000 0.477000 2.420000
v -0.405000 0.314000 2.420000
v -0.460000 0.020000 2.420000
v -0.380000 -0.256000 2.420000
v -0.158000 -0.465000 2.420000
v 0.151000 -0.446000 2.420000
v 0.429000 -0.292000 2.420000
v 0.420000 -0.010000 0.280000
v 0.319000 0.208000 0.280000
v 0.150000 0.389000 0.280000
v -0.091000 0.332000 0.280000
v -0.312000 0.231000 0.280000
v -0.370000 -0.010000 0.280000
v -0.255000 -0.210000 0.280000
v -0.097000 -0.371000 0.280000
v 0.131000 -0.352000 0.280000
v 0.344000 -0.245000 0.280000
v 0.730000 0.020000 0.550000
v 0.560000 0.390000 0.550000
v 0.266000 0.686000 0.550000
v -0.148000 0.629000 0.550000
v -0.492000 0.414000 0.550000
v -0.570000 0.020000 0.550000
v -0.476000 -0.362000 0.550000
v -0.163000 -0.636000 0.550000
v 0.254000 -0.608000 0.550000
v 0.624000 -0.397000 0.550000
v 0.370000 0.040000 0.950000
v 0.263000 0.246000 0.950000
v 0.104000 0.420000 0.950000
v -0.131000 0.382000 0.950000
v -0.327000 0.263000 0.950000
v -0.360000 0.040000 0.950000
v -0.336000 -0.189000 0.950000
v -0.150000 -0.359000 0.950000
v 0.094000 -0.312000 0.950000
v 0.312000 -0.201000 0.950000
v 0.450000 0.000000 1.350000
v 0.328000 0.282000 1.350000
v 0.107000 0.514000 1.350000
v -0.205000 0.447000 1.350000
v -0.489000 0.312000 1.350000
v -0.550000 0.000000 1.350000
v -0.432000 -0.270000 1.350000
v -0.221000 -0.495000 1.350000
v 0.095000 -0.476000 1.350000
v 0.385000 -0.323000 1.350000
v 0.600000 -0.040000 1.750000
v 0.453000 0.289000 1.750000
v 0.188000 0.540000 1.750000
v -0.170000 0.483000 1.750000
v -0.477000 0.307000 1.750000
v -0.570000 -0.040000 1.750000
v -0.437000 -0.358000 1.750000
v -0.185000 -0.611000 1.750000
v 0.179000 -0.592000 1.750000
v 0.502000 -0.405000 1.750000
v 0.320000 -0.020000 2.050000
v 0.242000 0.127000 2.050000
v 0.130000 0.256000 2.050000
v -0.040000 0.227000 2.050000
v -0.178000 0.139000 2.050000
v -0.200000 -0.020000 2.050000
v -0.162000 -0.167000 2.050000
v -0.047000 -0.286000 2.050000
v 0.120000 -0.267000 2.050000
v 0.283000 -0.196000 2.050000
v 0.360000 0.010000 2.280000
v 0.271000 0.192000 2.280000
v 0.131000 0.352000 2.280000
v -0.079000 0.314000 2.280000
v -0.263000 0.216000 2.280000
v -0.280000 0.010000 2.280000
v -0.231000 -0.172000 2.280000
v -0.085000 -0.313000 2.280000
v 0.119000 -0.294000 2.280000
v 0.311000 -0.202000 2.280000
v 0.400000 0.020000 2.420000
v 0.291000 0.232000 2.420000
v 0.127000 0.410000 2.420000
v -0.114000 0.372000 2.420000
v -0.316000 0.249000 2.420000
v -0.350000 0.020000 2.420000
v -0.291000 -0.192000 2.420000
v -0.124000 -0.360000 2.420000
v 0.117000 -0.341000 2.420000
v 0.340000 -0.227000 2.420000
f 10 9 8 7 6 5 4 3 2 1
f 1 2 12 11
f 2 3 13 12
f 3 4 14 13
f 4 5 15 14
f 5 6 16 15
f 6 7 17 16
f 7 8 18 17
f 8 9 19 18
f 9 10 20 19
f 10 1 11 20
f 11 12 22 21
f 12 13 23 22
f 13 14 24 23
f 14 15 25 24
f 15 16 26 25
f 16 17 27 26
f 17 18 28 27
f 18 19 29 28
f 19 20 30 29
f 20 11 21 30
f 21 22 32 31
f 22 23 33 32
f 23 24 34 33
f 24 25 35 34
f 25 26 36 35
f 26 27 37 36
f 27 28 38 37
f 28 29 39 38
f 29 30 40 39
f 30 21 31 40
f 31 32 42 41
f 32 33 43 42
f 33 34 44 43
f 34 35 45 44
f 35 36 46 45
f 36 37 47 46
f 37 38 48 47
f 38 39 49 48
f 39 40 50 49
f 40 31 41 50
f 41 42 52 51
f 42 43 53 52
f 43 44 54 53
f 44 45 55 54
f 45 46 56 55
f 46 47 57 56
f 47 48 58 57
f 48 49 59 58
f 49 50 60 59
f 50 41 51 60
f 51 52 62 61
f 52 53 63 62
f 53 54 64 63
f 54 55 65 64
f 55 56 66 65
f 56 57 67 66
f 57 58 68 67
f 58 59 69 68
f 59 60 70 69
f 60 51 61 70
f 61 62 72 71
f 62 63 73 72
f 63 64 74 73
f 64 65 75 74
f 65 66 76 75
f 66 67 77 76
f 67 68 78 77
f 68 69 79 78
f 69 70 80 79
f 70 61 71 80
f 71 72 82 81
f 72 73 83 82
f 73 74 84 83
f 74 75 85 84
f 75 76 86 85
f 76 77 87 86
f 77 78 88 87
f 78 79 89 88
f 79 80 90 89
f 80 71 81 90
f 91 92 93 94 95 96 97 98 99 100
f 91 101 102 92
f 92 102 103 93
f 93 103 104 94
f 94 104 105 95
f 95 105 106 96
f 96 106 107 97
f 97 107 108 98
f 98 108 109 99
f 99 109 110 100
f 100 110 101 91
f 101 111 112 102
f 102 112 113 103
f 103 113 114 104
f 104 114 115 105
f 105 115 116 106
f 106 116 117 107
f 107 117 118 108
f 108 118 119 109
f 109 119 120 110
f 110 120 111 101
f 111 121 122 112
f 112 122 123 113
f 113 123 124 114
f 114 124 125 115
f 115 125 126 116
f 116 126 127 117
f 117 127 128 118
f 118 128 129 119
f 119 129 130 120
f 120 130 121 111
f 121 131 132 122
f 122 132 133 123
f 123 133 134 124
f 124 134 135 125
f 125 135 136 126
f 126 136 137 127
f 127 137 138 128
f 128 138 139 129
f 129 139 140 130
f 130 140 131 121
f 131 141 142 132
f 132 142 143 133
f 133 143 144 134
f 134 144 145 135
f 135 145 146 136
f 136 146 147 137
f 137 147 148 138
f 138 148 149 139
f 139 149 150 140
f 140 150 141 131
f 141 151 152 142
f 142 152 153 143
f 143 153 154 144
f 144 154 155 145
f 145 155 156 146
f 146 156 157 147
f 147 157 158 148
f 148 158 159 149
f 149 159 160 150
f 150 160 151 141
f 151 161 162 152
f 152 162 163 153
f 153 163 164 154
f 154 164 165 155
f 155 165 166 156
f 156 166 167 157
f 157 167 168 158
f 158 168 169 159
f 159 169 170 160
f 160 170 161 151
f 81 82 162 161
f 82 83 163 162
f 83 84 164 163
f 84 85 165 164
f 85 86 166 165
f 86 87 167 166
f 87 88 168 167
f 88 89 169 168
f 89 90 170 169
f 90 81 161 170`
		}
	];

	let {
		msgs = [],
		busy = false,
		statusLine = null,
		onSend,
		onLaunchObjExample
	}: {
		msgs?: ChatMsg[];
		busy?: boolean;
		statusLine?: string | null;
		onSend?: (payload: { text: string; model: string; useProcedural?: boolean; imageDataUrl?: string }) => void;
		onLaunchObjExample?: (liveObj: string) => void;
	} = $props();

	let input = $state('');
	let selectedModel = $state<string>('gpt-5.5');
	let useProcedural = $state<boolean>(true);
	let attachedDataUrl = $state<string | undefined>(undefined);
	let fileInputEl: HTMLInputElement | undefined = $state();

	function clearAttachment() {
		attachedDataUrl = undefined;
		if (fileInputEl) fileInputEl.value = '';
	}

	function onPickImage(e: Event) {
		const inputEl = e.currentTarget as HTMLInputElement;
		const file = inputEl.files?.[0];
		if (!file || !file.type.startsWith('image/')) {
			clearAttachment();
			return;
		}
		const reader = new FileReader();
		reader.onload = () => {
			const r = reader.result;
			attachedDataUrl = typeof r === 'string' ? r : undefined;
		};
		reader.readAsDataURL(file);
	}

	function submit() {
		const text = input.trim();
		const img = attachedDataUrl;
		if ((!text && !img) || busy) return;
		onSend?.({ text, model: selectedModel, useProcedural, imageDataUrl: img });
		input = '';
		clearAttachment();
	}

	let canSend = $derived(Boolean((input.trim() || attachedDataUrl) && !busy));
	let promptExamples = $derived(useProcedural ? PROCEDURAL_EXAMPLES : LLM_ONLY_EXAMPLES);

	function usePrompt(example: { text: string; category: string }) {
		input = example.text;
	}

	function launchObjExample(example: { name: string; liveObj: string }) {
		onLaunchObjExample?.(example.liveObj);
	}
</script>

<div class="planner-chat-shell">
	<div class="planner-chat-thread" role="log">
		{#if msgs.length === 0}
			<div class="planner-chat-welcome">
				<p class="planner-chat-guide-copy">
					Describe a scene or ask for edits like "add a lamp", "remove the sphere", or "make the table red". You can
					attach a reference image instead of or in addition to text.
				</p>
				{#if OBJ_EXAMPLES.length > 0}
					<div class="planner-obj-examples">
						<h3 class="planner-obj-examples-title">Launch OBJ Examples</h3>
						<div class="planner-obj-grid">
							{#each OBJ_EXAMPLES as example (example.name)}
								<button
									type="button"
									class="planner-obj-chip"
									class:disabled={busy}
									disabled={busy}
									onclick={() => launchObjExample(example)}
								>
									<span class="planner-obj-chip-icon">📦</span>
									<span class="planner-obj-chip-name">{example.name}</span>
								</button>
							{/each}
						</div>
					</div>
				{/if}
				<div class="planner-prompt-examples">
					<h3 class="planner-prompt-examples-title">Quick Prompts</h3>
					<div class="planner-prompt-grid">
						{#each promptExamples as example (example.text)}
							<button
								type="button"
								class="planner-prompt-chip"
								class:disabled={busy}
								disabled={busy}
								onclick={() => usePrompt(example)}
							>
								<span class="planner-prompt-chip-category">{example.category}</span>
								<span class="planner-prompt-chip-text">{example.text}</span>
							</button>
						{/each}
					</div>
				</div>
			</div>
		{:else}
			{#each msgs as m (m)}
				<div
					class="planner-chat-row"
					class:assistant={m.role === 'assistant'}
					class:user={m.role === 'user'}
				>
					<div class="planner-chat-bubble">
						<div class="planner-chat-content">
							{#if m.imageDataUrl}
								<img
									class="planner-chat-msg-image"
									src={m.imageDataUrl}
									alt=""
								/>
							{/if}
							{#if m.content}
								<div class="planner-chat-msg-text">{m.content}</div>
							{/if}
						</div>
					</div>
				</div>
			{/each}
		{/if}
	</div>

	{#if statusLine}
		<div class="planner-status" role="status">{statusLine}</div>
	{/if}

	<div class="planner-chat-input-shell">
		{#if attachedDataUrl}
			<div class="planner-chat-attach-strip">
				<img class="planner-chat-attach-thumb" src={attachedDataUrl} alt="" />
				<button
					type="button"
					class="planner-chat-attach-clear"
					onclick={clearAttachment}
					disabled={busy}
					title="Remove image"
				>
					✕
				</button>
			</div>
		{/if}
		<textarea
			rows="2"
			placeholder="Ask for generation or iterative edits..."
			bind:value={input}
			disabled={busy}
			onkeydown={(e) => {
				if (e.key === 'Enter' && !e.shiftKey) {
					e.preventDefault();
					submit();
				}
			}}
		></textarea>
		<div class="planner-chat-input-toolbar">
			<div class="planner-chat-toolbar-left">
				<label class="planner-chat-model-label">
					<span class="visually-hidden">Model</span>
					<select bind:value={selectedModel} disabled={busy} class="planner-chat-model-select">
						{#each MODEL_OPTIONS as opt (opt.value)}
							<option value={opt.value}>{opt.label}</option>
						{/each}
					</select>
				</label>
				<label class="planner-chat-procedural-label">
					<input
						type="checkbox"
						bind:checked={useProcedural}
						disabled={busy}
						class="planner-chat-procedural-checkbox"
					/>
					<span class="planner-chat-procedural-text">Use tools</span>
				</label>
				<input
					bind:this={fileInputEl}
					type="file"
					accept="image/*"
					class="visually-hidden"
					id="live-obj-chat-image"
					onchange={onPickImage}
					disabled={busy}
				/>
				<label for="live-obj-chat-image" class="planner-chat-attach-label" title="Attach image">
					Attach
				</label>
			</div>
			<button type="button" class="send-button" disabled={!canSend} onclick={submit}>
				{busy ? '…' : 'Send'}
			</button>
		</div>
	</div>
</div>

<style>
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	.planner-chat-msg-image {
		display: block;
		max-width: 100%;
		max-height: 180px;
		border-radius: 10px;
		object-fit: contain;
		margin-bottom: 6px;
		background: rgba(0, 0, 0, 0.04);
	}

	.planner-chat-msg-text {
		white-space: pre-wrap;
		word-break: break-word;
	}

	.planner-chat-attach-strip {
		display: flex;
		align-items: flex-start;
		gap: 8px;
	}

	.planner-chat-attach-thumb {
		height: 48px;
		width: auto;
		max-width: 72px;
		border-radius: 8px;
		object-fit: cover;
		border: 1px solid rgba(0, 0, 0, 0.08);
	}

	.planner-chat-attach-clear {
		border: none;
		background: rgba(0, 0, 0, 0.06);
		border-radius: 999px;
		width: 28px;
		height: 28px;
		cursor: pointer;
		color: #666;
		font-size: 14px;
		line-height: 1;
		flex-shrink: 0;
	}

	.planner-chat-attach-clear:hover:not(:disabled) {
		background: rgba(0, 0, 0, 0.1);
		color: #1a1a1a;
	}

	.planner-chat-attach-clear:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.planner-chat-input-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		flex-wrap: wrap;
	}

	.planner-chat-toolbar-left {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
		flex: 1;
	}

	.planner-chat-model-label {
		margin: 0;
		min-width: 0;
	}

	.planner-chat-model-select {
		box-sizing: border-box;
		max-width: 140px;
		height: 32px;
		font-family: inherit;
		font-size: 12px;
		font-weight: 600;
		color: #333;
		border: 1px solid rgba(0, 0, 0, 0.12);
		border-radius: 999px;
		padding: 0 10px;
		background: rgba(255, 255, 255, 0.95);
		cursor: pointer;
	}

	.planner-chat-model-select:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}

	.planner-chat-procedural-label {
		margin: 0;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		font-weight: 600;
		color: #333;
		cursor: pointer;
		user-select: none;
	}

	.planner-chat-procedural-checkbox {
		width: 16px;
		height: 16px;
		accent-color: #0000eb;
		cursor: pointer;
	}

	.planner-chat-procedural-checkbox:disabled {
		cursor: not-allowed;
	}

	.planner-chat-procedural-text {
		line-height: 1;
	}

	.planner-chat-attach-label {
		box-sizing: border-box;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		height: 32px;
		padding: 0 10px;
		border-radius: 999px;
		border: 1px solid rgba(0, 0, 0, 0.12);
		background: rgba(0, 0, 0, 0.03);
		cursor: pointer;
		font-size: 12px;
		font-weight: 600;
		color: #333;
		flex-shrink: 0;
		line-height: 1;
	}

	.planner-chat-attach-label:hover {
		background: rgba(0, 0, 0, 0.06);
	}

	.planner-prompt-examples {
		margin-top: 20px;
		padding-top: 20px;
		border-top: 1px solid rgba(0, 0, 0, 0.08);
	}

	.planner-prompt-examples-title {
		margin: 0 0 12px;
		font-size: 13px;
		font-weight: 600;
		color: #333;
	}

	.planner-prompt-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 8px;
	}

	.planner-prompt-chip {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		padding: 10px 12px;
		background: rgba(0, 0, 235, 0.03);
		border: 1px solid rgba(0, 0, 235, 0.12);
		border-radius: 8px;
		cursor: pointer;
		text-align: left;
		transition: all 0.15s;
	}

	.planner-prompt-chip:hover:not(.disabled) {
		background: rgba(0, 0, 235, 0.08);
		border-color: rgba(0, 0, 235, 0.2);
		transform: translateY(-1px);
	}

	.planner-prompt-chip:active:not(.disabled) {
		transform: translateY(0);
	}

	.planner-prompt-chip.disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.planner-prompt-chip-category {
		font-size: 10px;
		font-weight: 600;
		color: #0000eb;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		margin-bottom: 4px;
	}

	.planner-prompt-chip-text {
		font-size: 12px;
		color: #334155;
		line-height: 1.4;
	}

	.planner-obj-examples {
		margin-top: 20px;
		padding-top: 20px;
		border-top: 1px solid rgba(0, 0, 0, 0.08);
	}

	.planner-obj-examples-title {
		margin: 0 0 12px;
		font-size: 13px;
		font-weight: 600;
		color: #333;
	}

	.planner-obj-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: 8px;
	}

	.planner-obj-chip {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 12px;
		background: rgba(0, 0, 235, 0.03);
		border: 1px solid rgba(0, 0, 235, 0.12);
		border-radius: 8px;
		cursor: pointer;
		text-align: left;
		transition: all 0.15s;
	}

	.planner-obj-chip:hover:not(.disabled) {
		background: rgba(0, 0, 235, 0.08);
		border-color: rgba(0, 0, 235, 0.2);
		transform: translateY(-1px);
	}

	.planner-obj-chip:active:not(.disabled) {
		transform: translateY(0);
	}

	.planner-obj-chip.disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.planner-obj-chip-icon {
		font-size: 16px;
		line-height: 1;
	}

	.planner-obj-chip-name {
		font-size: 12px;
		font-weight: 600;
		color: #0000eb;
		line-height: 1.4;
	}
</style>
