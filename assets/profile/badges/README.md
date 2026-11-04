# Insígnias do perfil

As dez insígnias são desenhos originais em uma grade de 64 px com espessura de
traço consistente, margem de segurança e duas cores. Mantêm sua identidade em
32–48 px: calendário, xícara, microfone, código, fone, broto, chama, escudo,
estrela e coração. Sem medalhas metálicas, pedras ou efeitos de brilho.

`scripts/build_profile_assets.py` é a fonte das geometrias compartilhadas. Execute
`python scripts/build_profile_assets.py` para reconstruir os dez SVGs e seus PNGs
transparentes de 256 px. O renderer usa os PNGs empacotados, sem instalar um motor
SVG na hospedagem. Não há arquivos privados de usuários nestes assets.

O perfil usa as fontes Montserrat Regular e SemiBold, incluídas em
`../fonts/` com a licença SIL Open Font License original (`OFL.txt`). Esses
arquivos de terceiros mantêm sua própria licença; os desenhos originais seguem
a licença do projeto.
