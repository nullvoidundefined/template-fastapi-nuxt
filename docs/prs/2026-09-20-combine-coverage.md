# Measure coverage across the unit and integration suites

Ticket: IAN-185 (slice IAN-166)
Date: 2026-09-20

## Summary

The 80 percent coverage floor measured only the unit suite, so any module proved by an integration test against real Postgres and Redis counted as entirely uncovered. This adds a `coverage` job that combines both suites' data and checks the floor once, against the whole. It changes no application code and no test.

It lands before PR 3 because PR 3's connection dependency and table code are integration-tested by design, and the gate as it stood would have counted them as zero.

## What changed

The unit and integration jobs now write coverage data and check nothing: each passes `--cov-fail-under=0` and directs its data to its own `COVERAGE_FILE`, then uploads it as an artifact. A new `coverage` job downloads both, runs `coverage combine`, and reports against the floor. The `ci` aggregate requires it, so it is covered by the existing `protect-merge` ruleset without changing what that ruleset names.

`[tool.coverage.run]` gains `relative_files`, which stops each runner's absolute working directory being baked into the recorded paths, where the two sets of data would refer to files that never match. Keeping the suites apart is `COVERAGE_FILE`'s job, one per suite.

## Architectural decisions

**Combine across jobs rather than merge the jobs.** Chosen because the integration job carries Postgres and Redis service containers and a longer timeout, and folding the unit suite into it would make every unit failure wait on container startup. The alternative considered was running both suites in one job; it is simpler, and it would have coupled the fastest feedback in the graph to the slowest setup.

**The floor moved rather than being relaxed.** The number is unchanged at 80 percent. The defect was where it was measured, not how high it was, and lowering it would have hidden the same problem behind a smaller number.

**The combine step asserts it combined two files.** `coverage combine` is content with whatever it finds, so a missing or misnamed artifact would quietly produce a lower total that looks like a real coverage drop. The step greps for the count and fails loudly instead, because a gate that silently measures half of its input is worse than no gate.

**`COVERAGE_FILE` per suite rather than renaming after the run.** In CI the two suites run on separate runners and cannot collide, but the same commands have to work locally, and naming each suite's data file up front is what makes a local run combine the same two files CI does.

## Testing

No unit test: this is CI configuration, and a test asserting that a YAML file contains a key asserts the file rather than the behavior.

Verified by running the sequence locally. The unit suite wrote `.coverage.unit`, the integration suite wrote `.coverage.integration` against the compose Postgres 17 and Redis 7, `coverage combine` reported `Combined 2 files`, and the combined report gave 97 percent over 316 statements against the 80 percent floor.

An earlier attempt renamed `.coverage` between the two runs and reported `Combined 1 file` and a false 59 percent, because coverage's `erase()` at the start of the second run glob-deleted the renamed file. That is what `COVERAGE_FILE` avoids. The pre-merge review then pointed out that the `parallel = true` this PR had also added was not what made any of it work, and re-running the same local sequence without it still reported `Combined 2 files` and 97 percent, so the setting was dropped.

The workflow was parsed and its job graph asserted: `coverage` needs `unit` and `integration`, and `ci` needs `coverage`. `download-artifact` is pinned to v7 to match the pinned `upload-artifact@v7` rather than to its own latest major, so the pair stays on one generation.

CI proves the half that cannot be proved locally: that the artifacts survive the round trip between runners.

## Reflection

Time since implementation: written immediately after the local verification, about twenty minutes after the branch was cut.

What I understand now that I did not at the start: a coverage floor is a claim about a codebase, and where it is measured decides what it actually claims. This one had been asserting "the unit suite covers 80 percent of the code" while reading as "the code is 80 percent covered", and the gap between those two sentences is exactly the integration tests, which are the ones exercising the code most likely to break in production. The number was never wrong; the sentence it appeared to support was.

What I got wrong first: two things, and the second is the one worth keeping.

I assumed renaming `.coverage` between runs was enough and wrote the local check that way. It reported `Combined 1 file` and a total of 59 percent, which I could have read as a genuine coverage problem and gone looking for uncovered modules. The thing that caught it was asserting on the combine count rather than on the percentage, and that is why the CI step now does the same.

Then, having been burned once, I added `parallel = true` and wrote a confident comment explaining why it was necessary. It was not, and the explanation was wrong about the mechanism: pytest-cov already measures with its own data suffix and combines within the job, so the setting's only effect here was widening the glob that `erase()` deletes, which is the very behavior I had just worked around. A fix that follows a debugging session is the easiest place to leave a plausible-sounding but untested belief, and the reviewer caught it by reading the tool rather than the comment.
