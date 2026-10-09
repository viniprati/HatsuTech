# Changelog

Todas as mudancas relevantes do HatsuTech passam a ser registradas neste
arquivo. O projeto segue [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-10-08

### Added

- exclusão do cargo VIP comum criado por `/vip` após 21 dias sem mensagens ou
  presença em voz fora do canal AFK pelo dono;
- início seguro da contagem para cargos existentes e nova janela de 21 dias após
  interrupções longas do monitoramento;
- tentativas posteriores e registro para revisão quando o Discord recusa a
  exclusão.

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
