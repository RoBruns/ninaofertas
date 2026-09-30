import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, apiFailure } from '../api/client'
import { errorMessage, type Phone } from '../api/management'
import { Field } from './Management'
import { useToast } from './useToast'

export function GroupInviteForm({ phones }: { phones: Phone[] }) {
  const [phoneId, setPhoneId] = useState(phones[0]?.id ?? '')
  const [invite, setInvite] = useState('')
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const save = useMutation({
    mutationFn: async () => {
      const result = await api.POST('/api/groups/from-invite', { body: { phone_id: phoneId, invite_link: invite } })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
    onSuccess: async (group) => {
      await queryClient.invalidateQueries({ queryKey: ['groups'] })
      setInvite('')
      showToast('Grupo cadastrado.', 'success')
      if (group.warning) showToast(group.warning, 'error')
    },
  })
  return <form className="form-grid columns" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
    <Field label="Telefone do convite"><select required value={phoneId} onChange={(event) => setPhoneId(event.target.value)}>{phones.map((phone) => <option key={phone.id} value={phone.id}>{phone.label}</option>)}</select></Field>
    <Field label="Link de convite do grupo"><input required value={invite} onChange={(event) => setInvite(event.target.value)} placeholder="https://chat.whatsapp.com/…" /></Field>
    <div className="form-actions"><button className="button primary" disabled={save.isPending || !phoneId}>Adicionar</button></div>
    {save.error && <p className="field-error" role="alert">{errorMessage(save.error)}</p>}
  </form>
}
