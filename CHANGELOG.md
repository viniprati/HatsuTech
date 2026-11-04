# Changelog

Todas as mudancas relevantes do HatsuTech passam a ser registradas neste
arquivo. O projeto segue [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- comando `/perfil` com cartão próprio do servidor, dez insígnias vetoriais
  originais, conquistas verificáveis e progresso, temas Café/Sakura/Meia-noite,
  descrição e até três destaques; privado por padrão, com compartilhamento opcional;
- persistência de conquistas e de até sete dias distintos de participação, sem
  armazenar conteúdo de mensagens; vencedores são registrados ao encerrar eventos;
- prévia local offline do perfil e reconstrução dos SVGs/PNGs por geometria
  compartilhada, usando fontes empacotadas com licença;
- relatório administrativo por DM para PRATI e Renk em cada exclusão de cargo
  VIP pessoal ou destaque realizada pelo bot, incluindo saída/banimento,
  inatividade, perda de elegibilidade e exclusão pelo painel do dono;
- script local `scripts/audit_vip_message_history.py` para analisar mensagens já
  existentes dos últimos dez dias no lobby por padrão, com opções para threads
  ou servidor inteiro, exportando JSON local com evidências e cobertura parcial
  quando houver falhas;
- script local `scripts/audit_vip_activity.py` para consultar a última atividade
  registrada dos donos de cargos, classificar históricos insuficientes e exportar
  JSON automaticamente em pasta ignorada pelo Git e CSV opcional, com leitura do
  MongoDB ou de backup JSON sem iniciar o bot.

### Changed

- encerramento dos eventos arquiva os pontos atuais de forma atômica para
  conceder a conquista ao vencedor correto, incluindo empates;
- exclusão de cargos VIP pessoais e destaques Monarch após dez dias sem atividade
  observada do dono, incluindo cargos personalizados vinculados manualmente;
- mensagens em qualquer canal, reações, comandos, botões, formulários e atividade
  em voz fora do AFK renovam a janela de inatividade;
- exclusão dos cargos pessoais quando o dono sai ou é banido, com novas tentativas
  para falhas e processamento de registros antigos marcados para revisão.

## [1.1.0] - 2026-10-08

### Added

- exclusão do cargo VIP comum criado por `/vip` após 21 dias sem mensagens ou
  presença em voz fora do canal AFK pelo dono;
- exclusão do destaque pessoal Monarch após 28 dias sem atividade do dono,
  preservando o cargo base Monarch;
- início seguro da contagem para cargos existentes e nova janela de 21 dias após
  interrupções longas do monitoramento;
- tentativas posteriores e registro para revisão quando o Discord recusa a
  exclusão, inclusive na desativação do destaque por perda de elegibilidade.
- limpeza após o prazo mesmo quando o dono saiu do servidor, depois de confirmar
  sua ausência pela API do Discord.

### Changed

- correções da remoção de cargos temporários e da exclusão manual de VIP;
- comandos de cargos temporários agrupados em `/cargo_temporario`;
- consultas administrativas de VIP, guildas, compras e estatísticas com painéis
  mais claros;
- confirmações administrativas para exclusão de guilda e alterações sensíveis.

## [1.0.4] - 2026-10-01

### Added

- auditoria administrativa por DM para os dois responsáveis configurados;
- notificações de alterações de saldo, resets, vínculos e temproles VIP;
- detecção de concessões e remoções manuais de VIP pelo Audit Log do Discord;
- persistência do resultado individual de cada entrega em `admin_audit_logs`;
- uma nova tentativa automática para falhas temporárias no envio das DMs.

### Changed

- alterações de saldo agora são notificadas independentemente de terem sido
  executadas pela equipe de eventos, por administradores ou pelo owner;
- destinatários podem ser definidos em `ADMIN_AUDIT_DM_USER_IDS`, mantendo
  PRATI e Renk como padrão;
- compras normais da loja continuam fora da auditoria administrativa por DM.

## [1.0.3] - 2026-10-01

Primeira versao de codigo formalmente identificada e publicada na branch
`main`.

### Added

- estoque global de cinco unidades para cada tipo de VIP da loja;
- comando `/eco loja_global`, separado da loja de lootboxes;
- indicadores visuais de disponibilidade e indisponibilidade;
- registros correlacionados de compras, falhas e estornos.

### Changed

- reposicoes de VIP, definidas pela Administracao, liberam os limites de
  compra para todos os usuarios da loja;
- a loja antiga nao oferece mais compra de VIPs.

[1.0.3]: https://github.com/viniprati/HatsuTech/compare/a8fa647...v1.0.3
[1.0.4]: https://github.com/viniprati/HatsuTech/compare/v1.0.3...v1.0.4
[1.1.0]: https://github.com/viniprati/HatsuTech/compare/v1.0.4...v1.1.0
