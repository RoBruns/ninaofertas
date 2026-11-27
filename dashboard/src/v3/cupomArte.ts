export interface EstiloLoja {
  nome: string;
  bg: string;
  fg: string;
  acento: string;
  badgeBg: string;
  badgeFg: string;
  sigla: string;
  logoUrl: string;
  precisaPillClaroNoOficial: boolean;
}

export interface PadraoCupomClient {
  estilo: "oficial" | "dark" | "personalizado";
  titulo: string;
  subtitulo: string;
  chamada: string;
  mostrarLogoLoja: boolean;
  mostrarArroba: boolean;
  templateMensagem: string;
  fundoDataUrl: string;
  linksPorLoja: Record<string, string>;
}

export const PADRAO_CUPOM_INICIAL: PadraoCupomClient = {
  estilo: "oficial",
  titulo: "CUPOM NOVO",
  subtitulo: "Aplique no carrinho antes de acabar",
  chamada: "Teste agora no link da mensagem",
  mostrarLogoLoja: true,
  mostrarArroba: true,
  templateMensagem: [
    "🎟️ *CUPOM NOVO — {loja}*",
    "",
    "Código: *{codigo}*",
    "👉 Teste agora nesse link: {link}",
    "",
    "Via {arroba}",
  ].join("\n"),
  fundoDataUrl: "",
  linksPorLoja: {},
};

export const ESTILOS_LOJA: Record<string, EstiloLoja> = {
  mercadolivre: {
    nome: "Mercado Livre",
    bg: "#FFE600",
    fg: "#2D3277",
    acento: "#2D3277",
    badgeBg: "#2D3277",
    badgeFg: "#FFE600",
    sigla: "ML",
    logoUrl: "/logos/mercadolivre-oficial.png",
    precisaPillClaroNoOficial: false,
  },
  shopee: {
    nome: "Shopee",
    bg: "#EE4D2D",
    fg: "#FFFFFF",
    acento: "#EE4D2D",
    badgeBg: "#EE4D2D",
    badgeFg: "#FFFFFF",
    sigla: "SP",
    logoUrl: "/logos/shopee.svg",
    precisaPillClaroNoOficial: true,
  },
  amazon: {
    nome: "Amazon",
    bg: "#131921",
    fg: "#FFFFFF",
    acento: "#FF9900",
    badgeBg: "#FF9900",
    badgeFg: "#131921",
    sigla: "AZ",
    logoUrl: "/logos/amazon.svg",
    precisaPillClaroNoOficial: true,
  },
  aliexpress: {
    nome: "AliExpress",
    bg: "#E62E04",
    fg: "#FFFFFF",
    acento: "#FF6A00",
    badgeBg: "#E62E04",
    badgeFg: "#FFFFFF",
    sigla: "AE",
    logoUrl: "/logos/aliexpress.svg",
    precisaPillClaroNoOficial: true,
  },
  awin: {
    nome: "Magalu",
    bg: "#0086FF",
    fg: "#FFFFFF",
    acento: "#0086FF",
    badgeBg: "#0086FF",
    badgeFg: "#FFFFFF",
    sigla: "MG",
    logoUrl: "/logos/magalu.png",
    precisaPillClaroNoOficial: false,
  },
  outra: {
    nome: "Cupom Especial",
    bg: "#181B22",
    fg: "#FFFFFF",
    acento: "#F06526",
    badgeBg: "#F06526",
    badgeFg: "#FFFFFF",
    sigla: "CP",
    logoUrl: "",
    precisaPillClaroNoOficial: false,
  },
};

// Logo padrao do projeto (apenas o bichinho, fundo transparente)
const LOGO_PROJETO_PADRAO_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="12 4 76 82" width="100" height="100">
  <rect x="46" y="10" width="8" height="14" rx="4" fill="#D94E0F"/>
  <circle cx="50" cy="11" r="6.5" fill="#F06526"/>
  <rect x="16" y="23" width="68" height="60" rx="22" fill="#F06526"/>
  <rect x="24" y="34" width="52" height="36" rx="14" fill="#111318"/>
  <rect x="34" y="45" width="9" height="14" rx="4.5" fill="#FFFFFF"/>
  <rect x="57" y="45" width="9" height="14" rx="4.5" fill="#FFFFFF"/>
  <rect x="45" y="75" width="10" height="3.5" rx="1.75" fill="#111318" opacity="0.35"/>
</svg>`;

export function obterLogoProjetoPadraoDataUrl(): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(LOGO_PROJETO_PADRAO_SVG)}`;
}

function carregarImagem(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    if (!src) return resolve(null);
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

export function limparTextoInterno(texto: string): string {
  if (!texto) return "";
  let s = texto.trim();
  s = s.replace(/^Capturado em:\s*/i, "");
  while (s.startsWith("[")) {
    let nivel = 0;
    let fim = -1;
    for (let i = 0; i < s.length; i++) {
      if (s[i] === "[") nivel++;
      else if (s[i] === "]") {
        nivel--;
        if (nivel === 0) {
          fim = i;
          break;
        }
      }
    }
    if (fim >= 0) {
      s = s.slice(fim + 1).trim();
    } else {
      break;
    }
  }
  s = s
    .replace(/·\s*Detectado automaticamente/gi, "")
    .replace(/Detectado automaticamente/gi, "")
    .trim();
  return s;
}

export function limparValidadePublica(validade: string): string {
  const v = (validade || "").trim();
  if (!v || /detectado automaticamente/i.test(v)) return "";
  return v;
}

export function montarLegendaCupom(params: {
  template: string;
  codigo: string;
  loja: string;
  link: string;
  arroba: string;
  valorMinimo?: number;
  validade?: string;
}): string {
  const est = ESTILOS_LOJA[params.loja] || ESTILOS_LOJA.outra;
  const linkLimpo = (params.link || "").trim();
  const valLimpa = limparValidadePublica(params.validade || "");
  const minimoTxt =
    params.valorMinimo && params.valorMinimo > 0
      ? `R$ ${params.valorMinimo.toFixed(0)}`
      : "";

  const linhas = (params.template || PADRAO_CUPOM_INICIAL.templateMensagem).split("\n");
  const renderizadas = linhas
    .map((linha) => {
      if (linha.includes("{link}") && !linkLimpo) return null;
      if (linha.includes("{arroba}") && !params.arroba.trim()) return null;
      if (linha.includes("{minimo}") && !minimoTxt) return null;
      if (linha.includes("{validade}") && !valLimpa) return null;
      return linha
        .replace(/\{loja\}/gi, est.nome)
        .replace(/\{codigo\}/gi, params.codigo.toUpperCase())
        .replace(/\{link\}/gi, linkLimpo)
        .replace(/\{arroba\}/gi, params.arroba.trim())
        .replace(/\{minimo\}/gi, minimoTxt)
        .replace(/\{validade\}/gi, valLimpa);
    })
    .filter((l): l is string => l !== null);

  return renderizadas.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

export async function renderizarArteCupomPng(params: {
  codigo: string;
  loja: string;
  arroba: string;
  logoProjetoDataUrl?: string;
  valorMinimo?: number;
  validade?: string;
  padrao: PadraoCupomClient;
}): Promise<string> {
  const canvas = document.createElement("canvas");
  canvas.width = 1080;
  canvas.height = 1080;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";

  const est = ESTILOS_LOJA[params.loja] || ESTILOS_LOJA.outra;
  const { padrao } = params;
  const isDark = padrao.estilo === "dark";
  const isPersonalizado = padrao.estilo === "personalizado" && Boolean(padrao.fundoDataUrl);

  // 1. Fundo
  if (isPersonalizado) {
    const bgImg = await carregarImagem(padrao.fundoDataUrl);
    if (bgImg) {
      const scale = Math.max(1080 / bgImg.width, 1080 / bgImg.height);
      const w = bgImg.width * scale;
      const h = bgImg.height * scale;
      ctx.drawImage(bgImg, (1080 - w) / 2, (1080 - h) / 2, w, h);
      ctx.fillStyle = "rgba(10, 12, 18, 0.36)";
      ctx.fillRect(0, 0, 1080, 1080);
    } else {
      ctx.fillStyle = est.bg;
      ctx.fillRect(0, 0, 1080, 1080);
    }
  } else if (isDark) {
    ctx.fillStyle = "#0F1219";
    ctx.fillRect(0, 0, 1080, 1080);
    ctx.fillStyle = est.bg;
    ctx.fillRect(0, 0, 1080, 22);
  } else {
    ctx.fillStyle = est.bg;
    ctx.fillRect(0, 0, 1080, 1080);
  }

  // 2. Logo oficial real da loja no topo
  if (padrao.mostrarLogoLoja && est.logoUrl) {
    const logoImg = await carregarImagem(est.logoUrl);
    if (logoImg && logoImg.naturalWidth > 0 && logoImg.naturalHeight > 0) {
      const maxW = 420;
      const maxH = 98;
      const ratio = Math.min(maxW / logoImg.naturalWidth, maxH / logoImg.naturalHeight);
      const drawW = logoImg.naturalWidth * ratio;
      const drawH = logoImg.naturalHeight * ratio;
      const centerX = 540;
      const centerY = 122;

      const usarPillBranco =
        (isDark || isPersonalizado)
          ? params.loja !== "awin"
          : est.precisaPillClaroNoOficial;

      if (usarPillBranco) {
        const pillW = drawW + 64;
        const pillH = drawH + 34;
        ctx.fillStyle = params.loja === "mercadolivre" && (isDark || isPersonalizado) ? "#FFE600" : "#FFFFFF";
        ctx.beginPath();
        ctx.roundRect(centerX - pillW / 2, centerY - pillH / 2, pillW, pillH, 24);
        ctx.fill();
      }

      ctx.drawImage(
        logoImg,
        centerX - drawW / 2,
        centerY - drawH / 2,
        drawW,
        drawH
      );
    }
  }

  // 3. Cartao principal centralizado
  const cardY = padrao.mostrarLogoLoja && est.logoUrl ? 216 : 150;
  const cardH = padrao.mostrarLogoLoja && est.logoUrl ? 764 : 780;

  ctx.save();
  ctx.shadowColor = "rgba(0, 0, 0, 0.14)";
  ctx.shadowBlur = 36;
  ctx.shadowOffsetY = 14;
  ctx.fillStyle = isDark ? "#181C26" : "rgba(255, 255, 255, 0.97)";
  ctx.beginPath();
  ctx.roundRect(76, cardY, 928, cardH, 40);
  ctx.fill();
  ctx.restore();

  if (isDark) {
    ctx.strokeStyle = "rgba(255,255,255,0.1)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.roundRect(76, cardY, 928, cardH, 40);
    ctx.stroke();
  }

  // 4. Pill do titulo (ex: CUPOM NOVO)
  const tituloTexto = (padrao.titulo || "CUPOM NOVO").toUpperCase();
  ctx.font = "800 30px system-ui, -apple-system, 'Segoe UI', sans-serif";
  const pillW = Math.min(720, Math.max(280, ctx.measureText(tituloTexto).width + 76));
  const pillX = (1080 - pillW) / 2;
  const pillY = cardY + 56;

  ctx.fillStyle = isDark ? est.bg : est.badgeBg;
  ctx.beginPath();
  ctx.roundRect(pillX, pillY, pillW, 62, 31);
  ctx.fill();

  ctx.fillStyle = isDark ? est.fg : est.badgeFg;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(tituloTexto, 540, pillY + 32);

  // 5. Subtitulo limpo
  const subTexto = padrao.subtitulo || "Aplique no carrinho antes de acabar";
  ctx.fillStyle = isDark ? "#A1A9B8" : "#4B5563";
  ctx.font = "600 32px system-ui, -apple-system, 'Segoe UI', sans-serif";
  ctx.fillText(subTexto.slice(0, 56), 540, pillY + 114);

  // 6. Caixa tracejada do codigo
  const boxY = pillY + 158;
  ctx.fillStyle = isDark ? "#0F1219" : "#F5F7FA";
  ctx.strokeStyle = isDark ? est.bg : est.acento;
  ctx.lineWidth = 5;
  ctx.setLineDash([16, 12]);
  ctx.beginPath();
  ctx.roundRect(142, boxY, 796, 194, 26);
  ctx.fill();
  ctx.stroke();
  ctx.setLineDash([]);

  // Codigo em destaque
  const codigo = params.codigo.toUpperCase();
  ctx.fillStyle = isDark ? "#FFFFFF" : "#111318";
  const fontSize = codigo.length > 14 ? 56 : codigo.length > 10 ? 70 : 88;
  ctx.font = `900 ${fontSize}px ui-monospace, 'Cascadia Mono', Consolas, monospace`;
  ctx.fillText(codigo, 540, boxY + 99);

  // 7. Chamada inferior
  const chamadaTxt = padrao.chamada || "Teste agora no link da mensagem";
  ctx.fillStyle = isDark ? "#E5E7EB" : "#1F2937";
  ctx.font = "700 34px system-ui, -apple-system, 'Segoe UI', sans-serif";
  ctx.fillText(chamadaTxt.slice(0, 54), 540, boxY + 258);

  // 8. Info extra (somente se houver minimo ou validade real)
  const validadeReal = limparValidadePublica(params.validade || "");
  const extras = [
    params.valorMinimo && params.valorMinimo > 0
      ? `Pedido mínimo R$ ${params.valorMinimo.toFixed(0)}`
      : null,
    validadeReal || null,
  ]
    .filter(Boolean)
    .join("  ·  ");

  if (extras) {
    ctx.fillStyle = isDark ? "#8B93A3" : "#6B7280";
    ctx.font = "500 28px system-ui, -apple-system, 'Segoe UI', sans-serif";
    ctx.fillText(extras, 540, boxY + 312);
  }

  // 9. Rodape com a LOGO DO PROJETO + @ da marca
  if (padrao.mostrarArroba) {
    const rodapeY = cardY + cardH - 64;
    const logoSrc = params.logoProjetoDataUrl?.trim() || obterLogoProjetoPadraoDataUrl();
    const projImg = await carregarImagem(logoSrc);
    const arrobaTxt = (params.arroba || "@ninaofertas").trim();

    ctx.font = "700 34px system-ui, -apple-system, 'Segoe UI', sans-serif";
    const textW = arrobaTxt ? ctx.measureText(arrobaTxt).width : 0;
    const iconSize = projImg ? 54 : 0;
    const gap = projImg && arrobaTxt ? 16 : 0;
    const totalW = iconSize + gap + textW;
    const startX = 540 - totalW / 2;

    if (projImg) {
      ctx.save();
      ctx.beginPath();
      ctx.roundRect(startX, rodapeY - iconSize / 2, iconSize, iconSize, 14);
      ctx.clip();
      const s = Math.max(iconSize / projImg.width, iconSize / projImg.height);
      const w = projImg.width * s;
      const h = projImg.height * s;
      ctx.drawImage(
        projImg,
        startX + (iconSize - w) / 2,
        rodapeY - iconSize / 2 + (iconSize - h) / 2,
        w,
        h
      );
      ctx.restore();
    }

    if (arrobaTxt) {
      ctx.fillStyle = isDark ? "#E5E7EB" : "#111318";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(arrobaTxt, startX + iconSize + gap, rodapeY + 2);
      ctx.textAlign = "center";
    }
  }

  return canvas.toDataURL("image/png");
}
