import type { Info, NodeStatus, Trial } from './api'

/** Plain-language labels for the verified node statuses. The colour never says more than this. */
export const STATUS_LABEL: Record<NodeStatus, string> = {
  culprit: 'Must change',
  cleared: 'Not needed',
  unverified: 'Not verified',
  abstained: 'Cannot say',
}

export const STATUS_MEANING: Record<NodeStatus, string> = {
  culprit:
    'Sherlock put this node back to known-good behaviour, re-ran the rest from the recording, and the run passed. It is in a smallest fix.',
  cleared:
    'Tested in a complete search and in none of the smallest fixes. Restoring it is not needed.',
  unverified:
    'Not proven either way: it was not tested, or the search stopped before deciding. No claim is made.',
  abstained:
    'Sherlock could not reach a verdict for this run, so it names no node. See the reason above.',
}

export const STATUS_ORDER: NodeStatus[] = ['culprit', 'cleared', 'unverified', 'abstained']

export const TRIAL_LABEL: Record<Trial['label'], string> = {
  fixes: 'Fixes the run',
  partly_helps: 'Partly helps',
  does_not_help: 'Does not help',
  cannot_say: 'Cannot say',
}

export const TRIAL_MEANING: Record<Trial['label'], string> = {
  fixes: 'With these nodes restored the check passes.',
  partly_helps: 'The check still fails, but more of it passes than in the original run.',
  does_not_help: 'The check still fails and nothing improved.',
  cannot_say: 'The trial needed something that was never recorded, so no result is claimed.',
}

export const GLOSSARY: { term: string; meaning: string }[] = [
  {
    term: 'Check (pass / fail)',
    meaning:
      'A written test of what a right answer looks like, for example "the answer mentions ISO 27001". A run passes when every part of the check passes, and fails otherwise. It is not an opinion.',
  },
  {
    term: 'Known-good run',
    meaning:
      'An earlier run of the same team on the same input that gave a correct answer. Sherlock copies its behaviour into the failed run, one node at a time, to see what changes.',
  },
  {
    term: 'Restore',
    meaning:
      'Put a node back to the behaviour it had in the known-good run, then replay the rest of the failed run from the recording. Nothing is called live.',
  },
  {
    term: 'Trial',
    meaning:
      'One restore-and-replay attempt on one set of nodes. The trial log lists every one, with its result.',
  },
  {
    term: 'Minimal set (smallest fix)',
    meaning:
      'A group of nodes that, restored together, make the run pass, where no smaller part of the group does. Two nodes can both be needed: restoring either alone still fails. There can be more than one minimal set.',
  },
  {
    term: 'Cannot say (abstain)',
    meaning:
      'Sherlock refuses to guess. It happens when a needed recording is missing, no known-good run was given, or the budget ran out. A "cannot say" always comes with a reason, and it is an honest answer, not a failure of the tool.',
  },
  {
    term: 'Clue',
    meaning:
      'A cheap hint, such as a node that raised an error or wrote nothing. Clues decide which nodes to test first. They are weaker than a trial and never decide a culprit.',
  },
  {
    term: 'Not tested (pruned)',
    meaning:
      'Skipped to save trials because it could not matter, for example it wrote the same output as the known-good run. Skipped is not the same as cleared.',
  },
]

/** The exact terminal command for step 3, filled in from the picks (placeholders until picked). */
export function buildCommand(info: Info | null, failed: string, good: string): string {
  const url = info?.source === 'langgraph' ? info.url : 'http://127.0.0.1:2024'
  const parts = [
    'sherlock-rec diagnose',
    `--thread-id ${failed || '<failed-run-id>'}`,
    `--good-run ${good || '<known-good-run-id>'}`,
    `--url ${url}`,
  ]
  if (info && info.sherlock_dir !== '.sherlock') {
    parts.push(`--out ${info.sherlock_dir}`)
  }
  return parts.join(' ')
}

export function setText(sets: string[][]): string {
  return sets.map((s) => `{${s.join(' + ')}}`).join(' or ')
}
