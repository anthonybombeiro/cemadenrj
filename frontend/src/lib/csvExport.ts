/** Exportação simples de tabela em CSV — sem depender de nenhuma lib
 * externa (a Rede Salvar do CEMADEN usa a extensão DataTables Buttons pra
 * isso, mas aqui não faz sentido puxar jQuery/DataTables só por causa desse
 * botão; um CSV client-side de ~20 linhas de código resolve igual). Ver
 * docs/referencia-visual-rede-salvar.md, seção 8. */

function escapeCsvCell(value: string): string {
  if (/[",\n;]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

export function downloadCsv(filename: string, headers: string[], rows: (string | number | null)[][]): void {
  const linhas = [headers, ...rows].map((linha) =>
    linha.map((celula) => escapeCsvCell(celula == null ? "" : String(celula))).join(";"),
  );
  // BOM UTF-8 no início — sem isso o Excel abre acentuação quebrada.
  const conteudo = "﻿" + linhas.join("\r\n");
  const blob = new Blob([conteudo], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
