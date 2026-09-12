import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SettingsModal } from './SettingsModal'
import { usePPTStore } from '../store/usePPTStore'

const SETTINGS = {
  openai_base_url: 'https://api.openai.com/v1',
  openai_api_key_set: false,
  default_model: 'gpt-4o',
  reasoning_model: 'gpt-4o',
  vision_model: 'gpt-4o',
  fast_model: 'gpt-4o-mini',
  enable_vision_loop: true,
  context_limit: '256k'
}

const MODELS = ['gpt-4o', 'gpt-4o-mini', 'claude-3-opus']

describe('SettingsModal model configuration', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === '/api/settings') {
        if (init?.method === 'POST') {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ success: true })
          })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => SETTINGS })
      }
      if (url === '/api/models') {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ models: MODELS }) })
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
    })
    vi.stubGlobal('fetch', fetchMock)
    usePPTStore.setState({ settingsOpen: true })
  })

  it('renders a picker for every model role after fetching the model list', async () => {
    render(<SettingsModal />)

    // Loaded settings populate all four roles.
    expect(await screen.findByDisplayValue('gpt-4o-mini')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /获取模型列表/ }))

    const pickers = await screen.findAllByRole('combobox')
    expect(pickers).toHaveLength(4)
  })

  it('applies a fetched model to the default model field on selection', async () => {
    render(<SettingsModal />)
    fireEvent.click(screen.getByRole('button', { name: /获取模型列表/ }))

    const pickers = await screen.findAllByRole('combobox')
    // First picker belongs to 默认模型 (Default).
    fireEvent.change(pickers[0], { target: { value: 'claude-3-opus' } })

    expect(screen.getByDisplayValue('claude-3-opus')).toBeInTheDocument()
  })

  it('persists the selected default model on save', async () => {
    render(<SettingsModal />)
    fireEvent.click(screen.getByRole('button', { name: /获取模型列表/ }))

    const pickers = await screen.findAllByRole('combobox')
    fireEvent.change(pickers[0], { target: { value: 'claude-3-opus' } })

    fireEvent.click(screen.getByRole('button', { name: /保存配置/ }))

    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(
        ([url, init]) => url === '/api/settings' && (init as RequestInit)?.method === 'POST'
      )
      expect(saveCall).toBeTruthy()
      const body = JSON.parse((saveCall![1] as RequestInit).body as string)
      expect(body.default_model).toBe('claude-3-opus')
      expect(body.fast_model).toBe('gpt-4o-mini')
    })
  })
})
