export function ImportErrors({ errors }: { errors: ReadonlyArray<{ line: number; message: string }> }) {
  if (!errors.length) return null
  return <div className="inline-error" role="alert"><strong>Arquivo recusado: nenhuma linha foi importada.</strong><ul>{errors.map((error) => <li key={`${error.line}-${error.message}`}>Linha {error.line}: {error.message}</li>)}</ul></div>
}
