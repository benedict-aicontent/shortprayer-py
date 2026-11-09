---
name: quote-background-image-generator
description: Generate subtle, Canva-ready quote background images (watercolor, vintage paper, faded botanicals). Asks only output count, aspect ratio, resolution and subtlety with defaults, then generates.
---

# Quote Background Image Generator

Generates finished, text-free background images for Canva quotes, inspired by soft watercolor washes, faded botanicals, vintage paper and collage textures, with an airy open center. This skill PRODUCES IMAGE FILES. It does not output a prompt for the user to copy.

## Step 1: Ask the four settings (and nothing else)
Ask exactly these four settings in a single AskUserQuestion call (4 questions), defaults first and labeled "(Recommended)". If AskUserQuestion is unavailable, ask in one short plain-text message showing the defaults and accept "defaults" as an answer.

| Setting | Default | Options |
|---|---|---|
| OUTPUT_COUNT | 3 | 3 (Recommended), 1, 5 (user may type another) |
| ASPECT_RATIO | 9:16 vertical | 9:16 (Recommended), 4:5, 1:1, 16:9 |
| RESOLUTION | 1080 x 1920 px | 1080 x 1920 (Recommended), 1440 x 2560, 2160 x 3840 |
| SUBTLETY_LEVEL | HIGH | HIGH (Recommended, very soft decor), MEDIUM (slightly more visible decor) |

Rules:
- Do NOT ask any other question, before or after. No follow-ups about style, palette, generator, text color or elements. Anything not stated uses the random system below.
- If the user already stated any setting in their message, do not ask for it again; use it. If they stated all four, skip the question and go straight to generation.
- If the ratio changes but the resolution is not chosen, scale the resolution proportionally (1:1 -> 1080x1080, 4:5 -> 1080x1350, 16:9 -> 1920x1080) and mention it in the final line.
- Treat "1920x1080 vertical" as 1080 x 1920 portrait.
- Go to Step 2 immediately after the answers arrive. Do not wait for further confirmation.

## Step 2: Generate the images
Create exactly OUTPUT_COUNT images, each a SEPARATE file at the chosen resolution and ratio.

Method, in order of preference:
1. If an image-generation tool is available in the session, call it once per image using a per-image brief built from the rules below (one call per image, never one call that asks for several).
2. If no image-generation tool exists, create each image procedurally with code (Python with numpy/Pillow, or SVG/HTML rendered to PNG): layered watercolor washes, paper grain, soft edges, faint gradients, and light hand-drawn style decorations built from shapes (petals, leaves, branches, butterflies, hills, lattice, dots, ink splatters). Be upfront in the final message that these were built in code rather than by a diffusion model.

Never claim to have generated images that were not produced. Save as PNG, then deliver each file to the user.

Create a task list for the run, and check each finished image (right size, no text, open center, no border) before sending.

### Hard output rules
- Each image is ONE continuous full-bleed composition filling the entire canvas edge to edge.
- NEVER combine several backgrounds on one canvas: no collages of backgrounds, grids, contact sheets, split screens, side-by-side, tiled layouts, multi-panel compositions, mockups, or preview sheets.
- No borders, frames, margins, frame-like vignettes, or white edges.
- No text of any kind (letters, numbers, fake quotes, watermarks, signatures). Newsprint texture, if used, must be illegible and very faint.
- No logos or brand marks. No people, faces, or hands. Do not draw known copyrighted characters.
- Never copy the references' exact layouts or objects; invent new combinations.

### Subtlety system (all decorative elements)
- HIGH: element apparent opacity ~35-65%, hero cluster ~5-12% of canvas, open space 50-65%.
- MEDIUM: opacity ~55-80%, hero cluster ~8-15%, open space 45-60%.
- Desaturated, tone-on-tone colors; soft, feathered, watercolor-bled edges; no hard outlines or heavy linework; light impressionistic detail; elements look absorbed into the paper (transparency, multiply-style layering, ghosting); no or extremely faint shadows; few elements with lots of breathing room; decor is never the loudest thing in the image.

### Composition rules
- Keep the center zone readable for quote text: middle 60% width x 50% height for 9:16 and 4:5; middle 60% x 60% for 1:1; middle 50% width x 60% height for landscape. Low contrast and uncluttered, but NOT a flat blank fill: it must carry subtle wash gradients, paper grain or faint texture.
- Concentrate decor toward corners and edges; elements may bleed off the edge; nothing floating in the exact center.
- Hierarchy: one small hero cluster, 1-2 quieter supporting clusters, a few tiny accents.
- Safe zones: keep decoration clear of the top and bottom ~8% (portrait) or left and right ~8% (landscape), ~6% for square, except soft washes that reach the edge.
- Must work with both dark and light quote text.

### Randomization system
For EACH image, independently roll one option from every category. Across the batch, no two images may share the same Style, Palette family, Layout, or Hero Element; re-roll repeats.

A) STYLE: soft watercolor wash with bleeding edges; faded vintage paper with ephemera traces; Japanese-inspired washi with layered ink-wash hills; pale herbarium pressed-flower impressions; dreamy gouache with soft brush strokes; mid-century organic abstract shapes with grain; dusty boho minimal with delicate line art; impressionist soft-focus landscape wash; ink-and-wash minimalism with faint gold leaf; antique parchment / old-letter look; low-saturation risograph layered shapes; cottagecore sketchbook with faint graph or dotted paper.

B) PALETTE FAMILY (vary exact shades): cream/peach/dusty blue/hint of gold; sage/ivory/warm beige/soft terracotta; blush/mauve/champagne/muted plum; lavender/powder blue/pearl/pale silver; mustard/ochre/burnt sienna/warm cream; muted teal/forest green/aged paper/brass; rose dust/sepia/tea-stained ivory; sky blue/seafoam/sand/soft coral; charcoal-navy/muted gold/warm ivory (darker, elegant); peach/apricot/butter yellow/sage. Harmonious, low to medium saturation.

C) DECORATIVE ELEMENTS (pick 2-4, never the same set twice): small butterflies, moths, dragonflies, tiny bird silhouettes, faded watercolor blossoms (peony, cherry blossom, magnolia, poppy, wildflowers), fine eucalyptus or olive sprigs, autumn leaves, ferns, pressed dried flowers, faint wax seal, ghosted stamps or postmarks, vintage envelope edge, folded fan, antique key, thin spectacles outline, dried grass, pampas wisps, moon phases, tiny stars, soft sun disc, cloud wisps, hills, gentle waves, faint lattice or asanoha/seigaiha pattern, light gold foil flecks, delicate ink splatters, torn paper edges, washi tape, hand-drawn dashed grid, very faded illegible architectural engraving, feathers, seed pods, shells, lace texture, thin ribbon.

D) HERO ELEMENT: one element from C as the lead accent, kept small and faded.

E) LAYOUT: small cluster in one top corner + tiny accent in the opposite bottom corner; soft ground washes or hills along the bottom + faint sprinkle at top; gentle diagonal drift top-right to bottom-left; two balanced opposite corners; slim edge-hugging botanical along one side bleeding off canvas; layered horizontal washes with one small floating cluster; a few tiny perimeter elements with hero in one corner; faint pattern band at top fading into a soft glow.

F) TEXTURE MIX (3-5, layered, texture is a main feature): watercolor bloom, cold-press paper grain, soft crumple creases, parchment stains, canvas weave, salt texture, dry-brush strokes, gouache opacity, subtle film grain, ink bleed, faint gold shimmer flecks, cotton rag edges, ghosted illegible newsprint, dust and speckle.

G) MOOD: serene morning glow; warm nostalgic sepia; airy spring freshness; quiet autumn dusk; moonlit calm; golden hour warmth; soft rainy-day melancholy; gentle pastel bloom.

### Avoid (negative list)
text, watermark, logo, border, frame, white edge, collage of backgrounds, grid, split screen, multi-panel, mockup, people, bold or oversized flowers, saturated flower colors, thick outlines, hard vector edges, sticker or pasted-on look, heavy drop shadows, dense foliage, crowded or busy composition, cluttered or flat-blank center, neon, oversaturation, harsh contrast, muddy colors, blur, pixelation, banding, artifacts, distorted anatomy, repeated identical elements in rows, clipart look, wrong aspect ratio or orientation.

## Step 3: Final message
After delivering all files, write a very short wrap-up: the settings used (note any auto-scaled resolution and, if applicable, that images were built in code), then one line per image listing its rolled Style, Palette, Hero Element and Layout. No other questions, no extra sections.
