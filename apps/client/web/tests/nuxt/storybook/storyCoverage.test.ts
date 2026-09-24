/**
 * Coverage test for B-39 (spec: B-39, slice 03 PR 4, US-AUTH-004).
 *
 * B-39 says every `components/ui/` component has a Storybook story, and the review focus on this
 * pull request is that the check reads Storybook's own index rather than the filesystem alone. The
 * reason is that a filename check is satisfied by a file that renders nothing: an empty
 * `Button.stories.ts`, a story file the `stories` glob in `.storybook/main.ts` does not match, or
 * one whose only export is a docs page all leave a correctly named file on disk and no story in
 * Storybook, so the visual-regression project has nothing to snapshot and a regression in that
 * component can never be caught.
 *
 * Storybook's indexer is asked for the index directly through `buildIndex`, which loads
 * `.storybook/main.ts`, applies its presets and statically indexes the story files the
 * configuration actually matches. It needs no built Storybook and no running dev server, but it
 * does spawn a Node process: the indexer resolves the index's `importPath` values against the
 * working directory, and a Vitest worker's working directory is not guaranteed to be this app, so
 * the child is given this app's directory explicitly and every path is compared as an absolute
 * one. That child is also why the timeout below is generous; loading the Nuxt Storybook preset is
 * the slow part.
 *
 * The component side of the comparison is read recursively from disk, so a component in a nested
 * folder counts, and the three components the design spec fixes (Button, Modal and Toast) are
 * asserted by name so the coverage cannot be satisfied by deleting a component.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { describe, it, expect } from 'vitest';

const webDirectory = resolve(import.meta.dirname, '../../..');
const uiComponentsDirectory = join(webDirectory, 'app/components/ui');
const storybookConfigDirectory = join(webDirectory, '.storybook');
const indexTimeoutInMilliseconds = 180_000;
const indexMarker = 'STORY_INDEX_JSON:';
const componentPattern = /\.vue$/;
const storyPattern = /\.stories\.[tj]s$/;

type StoryIndexEntry = {
    type?: string;
    importPath?: string;
};

type StoryIndex = {
    entries?: Record<string, StoryIndexEntry>;
};

const indexerScript = [
    "const { buildIndex } = await import('storybook/internal/core-server');",
    'const storyIndex = await buildIndex({ configDir: process.argv[1] });',
    `process.stdout.write('${indexMarker}' + JSON.stringify(storyIndex));`,
].join('\n');

/**
 * Report a missing Storybook as an assertion rather than as a stack trace, so the first run of
 * this file reads as "there is no Storybook yet" instead of as a broken test.
 */
function expectStorybookConfiguration(): void {
    expect(
        existsSync(storybookConfigDirectory),
        `Storybook needs its configuration at ${describeRelativeToApp(storybookConfigDirectory)}`,
    ).toBe(true);
}

/** Ask Storybook itself what it indexes, in a child process rooted at this app. */
function readStoryIndex(): StoryIndex {
    const output = execFileSync(
        process.execPath,
        ['--input-type=module', '-e', indexerScript, storybookConfigDirectory],
        { cwd: webDirectory, encoding: 'utf8', timeout: indexTimeoutInMilliseconds },
    );
    const marked = output.slice(output.indexOf(indexMarker) + indexMarker.length);
    return JSON.parse(marked) as StoryIndex;
}

/** Every story file Storybook actually indexed at least one story from, as absolute paths. */
function readIndexedStoryFiles(): Set<string> {
    const { entries = {} } = readStoryIndex();
    const storyFiles = Object.values(entries)
        .filter(function isStory(entry) {
            return entry.type === 'story';
        })
        .map(function readFile(entry) {
            return resolve(webDirectory, entry.importPath ?? '');
        });
    return new Set(storyFiles);
}

function listComponentFiles(directory: string): string[] {
    if (!existsSync(directory)) {
        return [];
    }
    return readdirSync(directory, { withFileTypes: true }).flatMap(function readEntry(entry) {
        const entryPath = join(directory, entry.name);
        if (entry.isDirectory()) {
            return listComponentFiles(entryPath);
        }
        if (storyPattern.test(entry.name) || !componentPattern.test(entry.name)) {
            return [];
        }
        return [entryPath];
    });
}

/** The story file a component's stories belong in: the sibling `<Name>.stories.ts`. */
function buildStoryFilePath(componentFile: string): string {
    const componentName = basename(componentFile, '.vue');
    return join(dirname(componentFile), `${componentName}.stories.ts`);
}

function describeRelativeToApp(file: string): string {
    return file.slice(webDirectory.length + 1);
}

describe('storybook story coverage', () => {
    it(
        'B-39: every component under components/ui has a story Storybook indexes',
        { timeout: indexTimeoutInMilliseconds },
        () => {
            expectStorybookConfiguration();
            const componentFiles = listComponentFiles(uiComponentsDirectory);
            const componentNames = componentFiles.map(function readName(file) {
                return basename(file, '.vue');
            });

            expect(componentNames).toEqual(expect.arrayContaining(['Button', 'Modal', 'Toast']));

            const indexedStoryFiles = readIndexedStoryFiles();
            const componentsWithoutAnIndexedStory = componentFiles
                .filter(function lacksStory(componentFile) {
                    return !indexedStoryFiles.has(buildStoryFilePath(componentFile));
                })
                .map(describeRelativeToApp);

            expect(componentsWithoutAnIndexedStory).toEqual([]);
        },
    );

    it(
        'B-39: every indexed story under components/ui belongs to a component beside it',
        { timeout: indexTimeoutInMilliseconds },
        () => {
            expectStorybookConfiguration();
            const componentStoryFiles = new Set(
                listComponentFiles(uiComponentsDirectory).map(buildStoryFilePath),
            );
            const orphanedStories = [...readIndexedStoryFiles()]
                .filter(function isUnderUiComponents(storyFile) {
                    return storyFile.startsWith(`${uiComponentsDirectory}/`);
                })
                .filter(function lacksComponent(storyFile) {
                    return !componentStoryFiles.has(storyFile);
                })
                .map(describeRelativeToApp);

            expect(orphanedStories).toEqual([]);
        },
    );
});
