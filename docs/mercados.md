# Las casas: todos los mercados, su historia y el marcador exacto

Hasta ahora de las cuotas se guardaba **el 1X2 y nada más**, en una fila por
partido que se sobrescribía: la cuota de apertura y la de cierre eran la misma
fila, y la primera se perdía. Y el precio no se volvía a pedir nunca: un partido
visto tres días antes llegaba al saque con la cuota de apertura.

Ahora se guarda **cada mercado, de cada casa, cada vez que se mira**:

```bash
cancha mercados "Girona vs Osasuna"           # las casas al lado de lo nuestro
cancha mercados --marcadores                  # quién acierta más en marcador exacto
cancha mercados --traer betfair               # cuotas de Betfair para los próximos días
cancha mercados --traer the-odds-api          # varias casas por región
```

En la interfaz es la tarjeta **«Lo que dicen las casas»** de cada partido. El
modelo lo tiene como herramienta (`mercados_partido`) y dentro del expediente.

## Lo que se ve de cada partido

_Ejemplo para ver la forma: **los números son inventados**, no es un resultado real._

```
                       nosotros  mercado  cuota    dif.
Gana el local               52%      46%   2.10    +6%  ←
Empate                      26%      28%   3.40    -2%
Más de 2,5 goles            55%      51%   1.90    +4%
Marcan los dos              58%      54%   1.80    +4%

Marcador exacto (betfair-exchange):
    nosotros   1-1 12.1%      mercado   1-1 12.6%
    nosotros   1-0 11.4%      mercado   1-0 10.1%
    nosotros   2-1  9.3%      mercado   0-0  8.8%
```

De cada suceso se coge **la casa que menos cobra**: es la que más se acerca a lo
que el mercado de verdad cree, y la más difícil de batir. Coger otra sería
ponerse el listón bajo. Donde nos separamos más de cinco puntos se marca, y
conviene leerlo bien: **lo más probable es que el mercado sepa algo que
nosotros no**. El registro dirá con el tiempo cuándo no.

También se ve **cómo se ha movido** la cuota desde la apertura. Una cuota que
baja es que entra dinero ahí, y las de las últimas horas —con las alineaciones ya
dentro— son las que más dicen. Sofascore manda la cuota de apertura en la misma
respuesta que la de ahora; antes se tiraba.

## Cada cuánto se vuelve a mirar

Según lo que falte para el saque: cada doce horas si faltan días, cada seis a
menos de tres días, cada hora el último día y **cada cuarto de hora las tres
últimas horas**, que es cuando el precio dice más. Una foto idéntica a la
anterior no se guarda: mirar diez veces un mercado que no se mueve no son diez
datos. Un partido ya jugado no se vuelve a mirar: lo último que se vio antes del
saque es su **cierre**.

## El marcador exacto

Es el mercado más interesante de todos: es la distribución completa de lo que
el mercado cree que va a pasar. Con él se ve qué resultados cree más probables,
y se mide contra la nuestra.

_Ejemplo para ver la forma: **los números son inventados**, no es un resultado real._

```
Marcador exacto, 214 partidos jugados:

                            nosotros   mercado
Prob. al que salió             9.8%     10.9%
Log score (más es mejor)     -2.512    -2.401
Acertó el primero             11.2%     12.6%
Estaba entre los 3            31.8%     34.1%
```

Lo que se mide no es «cuál tenía primero»: el 1-1 es el más probable casi
siempre y eso acierta poco y a todo el mundo igual. Se mide **cuánta
probabilidad le dio cada uno al marcador que salió**. Quien le dio un 14 % al
2-1 que acabó pasando sabía más que quien le dio un 8 %, aunque ninguno de los
dos lo tuviera primero.

Los dos se miden sobre **las mismas casillas**: los marcadores que listaba el
mercado más un «cualquier otro». Si el partido acabó 5-3 y el mercado no lo
listaba, lo que cuenta es lo que cada uno le daba a «cualquier otro».

Hacen falta 30 partidos para decir nada; por debajo, un par de 3-2 raros deciden
solos.

### Quitarle el margen

Una casa cobra repartiendo su margen entre las selecciones, pero no a partes
iguales: carga más a las improbables. En un 1X2 da casi igual cómo se quite; en
un marcador exacto con veinte resultados, no. Con más de cuatro selecciones se
usa el **método de potencia**, que le quita más margen a lo improbable: en un
mercado real, a un 4-2 le baja un 15 % y a un 1-1, un 3 %.

## Otras fuentes: Betfair y The Odds API

Sofascore enseña los mercados de **una** casa. Para más:

**[Betfair Exchange](https://developer.betfair.com/exchange-api/)** es una bolsa:
los precios los ponen apostantes contra apostantes y Betfair solo cobra
comisión, así que su margen es casi nulo y **su marcador exacto es lo más
parecido a la distribución real que hay en público**. Tiene API oficial con
una clave gratuita (con unos segundos de retraso, que para esto sobran).

1. Crea la clave de aplicación retrasada en developer.betfair.com.
2. Ponla en **Ajustes → Cuotas**, con tu usuario y contraseña. Una cuenta
   española va con jurisdicción `es`: con la otra el acceso falla sin más.

**[The Odds API](https://the-odds-api.com/)** junta varias casas por región con
una sola clave. Tiene capa gratuita con un tope de peticiones al mes; cada liga,
mercado y región cuentan del cupo.

Las dos escriben en el mismo sitio que Sofascore, así que el resto del programa
no sabe de dónde vino cada cuota. Los partidos se emparejan con los nuestros por
hora y por **los dos nombres de equipo** («Girona FC» y «Girona» son el mismo;
el Real Madrid y el Atlético no). Si no hay pareja clara, no se empareja: mejor
sin cuotas que con las de otro partido. Lo que se queda sin pareja se enseña.

Las claves son secretos: no salen nunca en la página, y el fichero de ajustes
queda solo para tu usuario.

### Lo que no hay, a propósito

**Rascar la web de bet365.** Existen programas que lo hacen, pero va contra sus
condiciones y se rompen cada vez que cambian la página. Para algo que se quiera
vender, no. Lo mismo con los rascadores de OddsPortal, que además dicen en su
propia documentación que no son para uso comercial.

## En el registro

Con todos los mercados guardados, el registro ya tiene precio con el que
compararse en **goles, «ambos marcan», córners, tarjetas y marcador exacto**,
no solo en el 1X2; y el mercado concursa en la [clasificación](agentes.md) en
todos ellos.

El marcador exacto va **aparte** del balance general. Son treinta sucesos por
partido casi todos a un uno por ciento que no pasa: mezclados con el resto, el
Brier sale bueno por acertar que el 5-3 no ocurre, y la clasificación entera se
deformaría.
