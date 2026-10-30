/**
 * Asserts the English and Arabic dictionaries are structurally identical and
 * that every `t.<path>` reference in the source tree resolves.
 *
 * This is the check that keeps a translated UI honest: adding a string to one
 * language and forgetting the other is invisible at build time (a missing key
 * degrades to English rather than crashing), so it has to be caught here.
 *
 * Run with: npm run check:i18n
 */

import { readdir, readFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(here, '..')

/** Directories walked for `t.<path>` references. */
const SOURCE_DIRS = ['app', 'components', 'lib']

/** Files skipped: they *are* the dictionary. */
const SKIP = new Set(['lib/i18n.js', 'scripts/check-i18n.mjs'])

function flatten(value, prefix = '', out = new Map()) {
  // Arrays are leaves here, not nodes: `t.hero.documents` is a list of strings
  // the component maps over, and recursing into it would produce indices like
  // `hero.documents.0` that no source file ever references.
  if (Array.isArray(value)) {
    out.set(prefix, value)
    return out
  }
  if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      flatten(child, prefix ? `${prefix}.${key}` : key, out)
    }
    return out
  }
  out.set(prefix, value)
  return out
}

async function* walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      yield* walk(full)
    } else if (/\.(js|jsx|mjs|ts|tsx)$/.test(entry.name)) {
      yield full
    }
  }
}

const problems = []

const dictionaryModule = await import(
  pathToFileURL(path.join(frontendRoot, 'lib', 'i18n.js')).href
)
const en = flatten(dictionaryModule.getDictionary('en'))
const ar = flatten(dictionaryModule.getDictionary('ar'))

// ---------------------------------------------------------------- structure
for (const key of en.keys()) {
  if (!ar.has(key)) problems.push(`missing in AR: ${key}`)
}
for (const key of ar.keys()) {
  if (!en.has(key)) problems.push(`missing in EN: ${key}`)
}

// Every leaf in a translation dictionary should be a string, or an array whose
// entries the component maps over. Both are safe to render directly; a bare
// object is not, because it has no `toString` worth showing a student.
for (const [language, dict] of [
  ['EN', en],
  ['AR', ar],
]) {
  for (const [key, value] of dict) {
    if (typeof value === 'string') continue
    if (Array.isArray(value)) continue
    problems.push(`${language}: ${key} is a ${typeof value}, expected a string or an array`)
  }
}

// -------------------------------------------------------------- references
const references = new Map()

for (const dirName of SOURCE_DIRS) {
  const dir = path.join(frontendRoot, dirName)
  if (!existsSync(dir)) continue

  for await (const file of walk(dir)) {
    const relative = path.relative(frontendRoot, file).split(path.sep).join('/')
    if (SKIP.has(relative)) continue

    const source = await readFile(file, 'utf8')
    // Captures the *whole* path, so `t.auth.fields.email` is one key rather
    // than a bare `t.auth`. Bracket access with a literal key
    // (`t['chat']['newChat']`) is folded in too; a computed bracket
    // (`t.auth.departments[option.key]`) simply ends the match at the longest
    // literal prefix, which is still a key that must exist.
    const pattern = /\bt((?:\.\s*[A-Za-z_$][\w$]*)+(?:\[\s*['"`][^'"`]+['"`]\s*\])*)/g

    let match
    while ((match = pattern.exec(source)) !== null) {
      // Skip comments; `t.` at the start of a docstring line is not a lookup.
      const lineStart = source.lastIndexOf('\n', match.index) + 1
      const line = source.slice(lineStart, source.indexOf('\n', match.index))
      if (/^\s*(\/\/|\*|\/\*)/.test(line)) continue

      // Normalise `a. b ['c']` -> `a.b.c`.
      const key = match[1]
        .replace(/\[\s*['"`]([^'"`]+)['"`]\s*\]/g, '.$1')
        .replace(/\.\s+/g, '.')
        .replace(/^\.+|\.+$/g, '')

      if (!key) continue

      if (!references.has(key)) references.set(key, new Set())
      references.get(key).add(relative)
    }
  }
}

// `t.hero.documents.map(...)` refers to the dictionary key `hero.documents`,
// not to a `.map` key. Strip a trailing method call before resolving.
const METHOD_SUFFIX = /\.(map|filter|find|forEach|some|every|reduce|at|length|join)$/

for (const [key, files] of references) {
  // Skip anything with a dynamic tail; those cannot be verified statically.
  if (key.includes('{') || key.includes('$')) continue

  const normalized = key.replace(METHOD_SUFFIX, '')
  if (!references.has(normalized) && normalized !== key) {
    // Re-file it under the resolved name so the report is accurate.
    references.set(normalized, (references.get(normalized) ?? new Set()).union(files))
    references.delete(key)
  }
}

for (const [key, files] of references) {
  if (key.includes('{') || key.includes('$')) continue

  // A key is valid when it is a leaf, or an *intermediate* node. The latter is
  // reachable through bracket access - `t.auth.departments[option.key]` - which
  // the static scan can only resolve to the prefix.
  const isLeaf = en.has(key)
  const isNode = [...en.keys()].some((candidate) => candidate.startsWith(`${key}.`))

  if (!isLeaf && !isNode) {
    problems.push(`undefined key referenced: ${key} (${[...files].join(', ')})`)
  }
}

// ------------------------------------------- dynamic department label lookup
// `t.auth.departments[option.key]` in the register form is driven by
// DEPARTMENT_OPTIONS, so assert every one of them exists rather than relying
// on the static scan above.
const authRulesModule = await import(
  pathToFileURL(path.join(frontendRoot, 'lib', 'authRules.js')).href
)
for (const option of authRulesModule.DEPARTMENT_OPTIONS) {
  for (const [language, dict] of [
    ['EN', en],
    ['AR', ar],
  ]) {
    const key = `auth.departments.${option.key}`
    if (!dict.has(key)) {
      problems.push(`${language}: department label missing for ${option.value} (${key})`)
    }
  }
}

// --------------------------------------------------------------------- report
if (problems.length > 0) {
  console.error(`\ni18n check FAILED (${problems.length} problem(s)):\n`)
  for (const problem of problems) console.error(`  - ${problem}`)
  process.exit(1)
}

console.log(`i18n check passed: ${en.size} keys in both EN and AR,`)
console.log(`${references.size} distinct t.* references all resolve.`)
