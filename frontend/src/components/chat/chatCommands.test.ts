import { describe, expect, it } from 'vitest'
import { CHAT_COMMANDS, matchCommands, parseCommand } from './chatCommands'

describe('chatCommands', () => {
  it('exposes the core command set', () => {
    const names = CHAT_COMMANDS.map((c) => c.name)
    expect(names).toEqual(expect.arrayContaining(['compress', 'new', 'review', 'plan', 'help']))
  })

  it('matches commands by prefix', () => {
    expect(matchCommands('re').map((c) => c.name)).toEqual(['review'])
    expect(matchCommands('').length).toBe(CHAT_COMMANDS.length)
    expect(matchCommands('zzz')).toHaveLength(0)
  })

  it('parses a command with arguments', () => {
    const parsed = parseCommand('/review 3')
    expect(parsed?.command.name).toBe('review')
    expect(parsed?.args).toBe('3')
  })

  it('parses a bare command', () => {
    const parsed = parseCommand('/plan')
    expect(parsed?.command.name).toBe('plan')
    expect(parsed?.args).toBe('')
  })

  it('returns null for non-commands and unknown commands', () => {
    expect(parseCommand('hello')).toBeNull()
    expect(parseCommand('/nope')).toBeNull()
  })
})
