/** Tests for the prompt shown before a schedule is generated.
 *
 * The point of this dialog is that nothing has been written when it opens, so
 * the escape routes matter as much as the two actions: it exists partly to make
 * an accidental click on "Generate schedule" harmless. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { GenerateDialog } from './GenerateDialog'

function draw(props: { horizonDays?: number; busy?: boolean } = {}) {
  const onGenerate = vi.fn()
  const onClose = vi.fn()
  render(
    <GenerateDialog
      horizonDays={props.horizonDays ?? 5}
      busy={props.busy ?? false}
      onGenerate={onGenerate}
      onClose={onClose}
    />,
  )
  return { onGenerate, onClose }
}

const keep = () => screen.getByRole('button', { name: 'Keep settled periods' })
const rebuild = () =>
  screen.getByRole('button', { name: 'Regenerate settled periods too' })

describe('what it explains', () => {
  it('names how much of the schedule is settled', () => {
    draw({ horizonDays: 5 })

    expect(screen.getByText(/next 5 days/)).toBeInTheDocument()
  })

  it('says "day" when the horizon is a single one', () => {
    draw({ horizonDays: 1 })

    expect(screen.getByText(/next 1 day\b/)).toBeInTheDocument()
  })
})

describe('the two choices', () => {
  it('keeps settled periods by default, as an additive pass', async () => {
    const { onGenerate } = draw()

    await userEvent.click(keep())

    expect(onGenerate).toHaveBeenCalledWith({ strategy: 'additive' })
  })

  it('overrides the freeze when the user asks for a rebuild', async () => {
    const { onGenerate } = draw()

    await userEvent.click(rebuild())

    expect(onGenerate).toHaveBeenCalledWith({ strategy: 'rebuild' })
  })

  it('warns that a rebuild moves work already planned around', () => {
    draw()

    expect(screen.getByText(/may already have planned around/)).toBeInTheDocument()
  })
})

describe('getting out of it', () => {
  it('closes from the corner button without generating anything', async () => {
    const { onGenerate, onClose } = draw()

    await userEvent.click(screen.getByRole('button', { name: 'Close' }))

    expect(onClose).toHaveBeenCalledOnce()
    expect(onGenerate).not.toHaveBeenCalled()
  })

  it('closes from Cancel', async () => {
    const { onGenerate, onClose } = draw()

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onClose).toHaveBeenCalledOnce()
    expect(onGenerate).not.toHaveBeenCalled()
  })

  it('closes when the backdrop is clicked', async () => {
    const { onClose } = draw()

    await userEvent.click(screen.getByRole('presentation'))

    expect(onClose).toHaveBeenCalledOnce()
  })

  it('stays open when the dialog itself is clicked', async () => {
    const { onClose } = draw()

    await userEvent.click(screen.getByRole('dialog'))

    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('while it is working', () => {
  it('disables every control so nothing is submitted twice', () => {
    draw({ busy: true })

    // The primary action reports progress in place, so it is no longer
    // reachable under its idle name.
    for (const name of ['Generating…', 'Regenerate settled periods too', 'Cancel', 'Close']) {
      expect(screen.getByRole('button', { name })).toBeDisabled()
    }
    expect(screen.queryByRole('button', { name: 'Keep settled periods' })).toBeNull()
  })
})
