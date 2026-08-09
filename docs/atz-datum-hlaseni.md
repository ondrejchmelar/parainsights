# Hlášení chyby v datech ATZ (LKR315A) — návrh e-mailu

Adresát: `aim@ans.cz` (AIM Centre, ŘLP ČR, Navigační 787, 252 61 Jeneč).
Kontakt ověřen na <https://aim.rlp.cz/?lang=en&p=contact>.

Čísla v textu jsou spočítaná nad publikací `LKR315A.json` z 6. 8. 2026 kódem
v `airspaces/atz.py`; přepočítat před odesláním příkazem:

```bash
.venv/bin/python -m airspaces.cli --report
```

---

**Předmět:** LKR315A – systematický posun geometrie ATZ o ~117 m k JZ

Dobrý den,

při zpracování publikace zeměpisných zón pro bezpilotní systémy
(`https://aim.rlp.cz/data/uas/2026_08_06/actual/LKR315A.json`) pro potřeby
plánování letů padákových kluzáků jsem narazil na systematickou odchylku
v poloze polygonů ATZ. Rád bych ji nahlásil pro případ, že jde o chybu
v převodu souřadnic, o které zatím nevíte.

**Zjištění**

Soubor obsahuje 82 prvků. U 67 z nich lze hranici proložit kružnicí s maximální
odchylkou do 8 m; poloměr vychází 5 500,3 m (směrodatná odchylka 0,23 m), tedy
přesně publikovaných 5,5 km. Geometrie je tedy generovaná korektně.

Střed těchto 67 kružnic však neleží ve vztažném bodě letiště. Odchylka je
systematická:

| veličina | hodnota |
|---|---|
| vzdálenost středu ATZ od ARP | průměr **116,9 m** (min 29,1 m, max 134,4 m) |
| azimut odchylky | průměr **226°** (směrodatná odchylka 15°) |
| složky | východ −84,7 m, sever −78,3 m |
| počet měřených zón | 67 |

Střed ATZ tedy leží zhruba 117 m **jihozápadně** od vztažného bodu letiště.

**Ověření proti dvěma nezávislým zdrojům**

Aby bylo zřejmé, který údaj je odchýlený, porovnal jsem vztažné body ze dvou
na sobě nezávislých zdrojů:

| porovnání | průměrná odchylka |
|---|---|
| ARP z VFR příručky (`aim.rlp.cz/vfrmanual`) vs. databáze OurAirports | **7,3 m** |
| střed ATZ z LKR315A vs. databáze OurAirports | **109,8 m** |

Vaše vlastní VFR příručka a nezávislá databáze se shodují na 7 m, zatímco
soubor zón se od obou liší o zhruba 110 m stejným směrem. Odchýlený je tedy
soubor zón, nikoli vztažné body.

**Příklady** (souřadnice WGS84, desetinné stupně):

| ICAO | střed ATZ z LKR315A | ARP dle VFR příručky | odchylka |
|---|---|---|---|
| LKBA | 48,790289 N, 16,891168 E | 48,790833 N, 16,892500 E | 115 m |
| LKBE | 49,740102 N, 14,643624 E | 49,740833 N, 14,644722 E | 113 m |
| LKBO | 49,669931 N, 17,293540 E | 49,670556 N, 17,295000 E | 126 m |
| LKCB | 50,065554 N, 12,411976 E | 50,066389 N, 12,412778 E | 109 m |
| LKCE | 50,708596 N, 14,565507 E | 50,709444 N, 14,566667 E | 125 m |

**Domněnka o příčině**

Konstantní velikost i směr odchylky odpovídají převodu mezi S-JTSK a WGS84
provedenému bez transformační tabulky (bez gridu), tedy pouze přes Helmertovu
transformaci se zaokrouhlenými parametry, případně úplně bez datového posunu.
Rozsah 110–130 m je pro takový případ typický. Pokud se geometrie generuje
bufferem v Křovákově zobrazení a následně převádí do WGS84, bylo by dobré
ověřit právě tento krok.

**Praktický dopad**

Pro pilota je 117 m na poloměru 5 500 m zanedbatelné. Pro provozovatele
bezpilotních systémů, kteří se podle těchto dat řídí přímo, to ale znamená, že
hranice zóny je posunutá o více než sto metrů — na jedné straně letiště zóna
končí dříve, než by měla.

Souřadnice si samozřejmě rád upřesním nebo pošlu celý výpočet, pokud to pomůže.

S pozdravem
