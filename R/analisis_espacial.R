# R/analisis_espacial.R
#
# Análisis espacial del voto presidencial 2022 (Brasil), sobre los insumos de
# src/geo/insumos_espaciales.py. Decisión del 2026-10-02: hacerlo en R.
#
#   1. Focos del voto (LISA, Moran local) en municípios y, dentro de cada estado,
#      en las áreas de escuela. Moran global como resumen.
#   2. Focos de cambio 2018 -> 2022 (Getis-Ord Gi*) en municípios.
#   3. GWR (regresión geográficamente ponderada): cómo varía el efecto del Censo
#      sobre el voto según el lugar (municípios, kernel bisquare adaptativo, AICc).
#   4. Regionalización SKATER por estado: regiones contiguas que votan parecido,
#      tantas como regiões imediatas tiene el estado.
#   5. Accesibilidad: distancia a la escuela y abstención (modelo de error espacial
#      en municípios; MCO con efectos fijos de UF en escuelas).
#
# Salida: data/processed/geo/_espacial/<fecha_utc>/
#   municipios.gpkg (resultados por município), escuelas_lisa.csv,
#   accesibilidad_deciles.csv, resumen.json
#
# Uso (desde la raíz del proyecto):
#   Rscript R/analisis_espacial.R

lib <- file.path(Sys.getenv("LOCALAPPDATA"), "R", "win-library", "4.6")
if (dir.exists(lib)) .libPaths(c(lib, .libPaths()))
suppressPackageStartupMessages({
  library(sf); library(spdep); library(rgeoda); library(GWmodel); library(spatialreg); library(jsonlite)
})
sf_use_s2(FALSE)
set.seed(2026)
PERM <- 999
ALFA <- 0.01   # significancia de LISA y Gi* (con 999 permutaciones)

nac <- "data/processed/geo/_nacional"
geo <- "data/processed/geo"
out <- file.path("data/processed/geo/_espacial", format(Sys.time(), "%Y-%m-%dT%H%M%SZ", tz = "UTC"))
dir.create(out, recursive = TRUE, showWarnings = FALSE)
msg <- function(...) cat(format(Sys.time(), "%H:%M:%S"), sprintf(...), "\n")
res <- list()

mun <- st_read(file.path(nac, "municipios.gpkg"), quiet = TRUE)
mun <- st_make_valid(mun)
msg("Municípios: %d", nrow(mun))

# ---------------------------------------------------------------------------
# 1. Focos del voto: Moran global y LISA en municípios
# ---------------------------------------------------------------------------
lisa_etiqueta <- c("No significativo", "Alto-Alto", "Bajo-Bajo", "Bajo-Alto", "Alto-Bajo", "Sin vecinos", "Sin dato")
m1 <- mun[!is.na(mun$lula_2v), ]
w_q <- queen_weights(m1)
lisa <- local_moran(w_q, m1["lula_2v"], permutations = PERM, significance_cutoff = ALFA)
m1$lisa_lula <- lisa_labels(lisa)[lisa_clusters(lisa) + 1]
m1$lisa_lula_p <- lisa_pvalues(lisa)
nb <- poly2nb(m1, queen = TRUE)
lw <- nb2listw(nb, style = "W", zero.policy = TRUE)
mg <- moran.test(m1$lula_2v, lw, zero.policy = TRUE)
res$moran_municipios <- list(I = unname(mg$estimate[1]), p = mg$p.value,
                             clusters = as.list(table(m1$lisa_lula)))
msg("Moran I municípios (Lula 2v): %.3f", mg$estimate[1])
mun <- merge(mun, st_drop_geometry(m1)[, c("codigo", "lisa_lula", "lisa_lula_p")], by = "codigo", all.x = TRUE)

# ---------------------------------------------------------------------------
# 2. Focos de cambio 2018 -> 2022 (Gi*)
# ---------------------------------------------------------------------------
m2 <- mun[!is.na(mun$cambio_2018_2022), ]
w2 <- queen_weights(m2)
gi <- local_gstar(w2, m2["cambio_2018_2022"], permutations = PERM, significance_cutoff = ALFA)
lab <- lisa_labels(gi)[lisa_clusters(gi) + 1]
m2$gi_cambio <- ifelse(lab == "High-High", "Foco de suba de Lula", ifelse(lab == "Low-Low", "Foco de baja de Lula", lab))
m2$gi_cambio_p <- lisa_pvalues(gi)
res$gi_cambio <- as.list(table(m2$gi_cambio))
mun <- merge(mun, st_drop_geometry(m2)[, c("codigo", "gi_cambio", "gi_cambio_p")], by = "codigo", all.x = TRUE)
msg("Gi* cambio: %s", paste(names(res$gi_cambio), unlist(res$gi_cambio), collapse = "; "))

# ---------------------------------------------------------------------------
# 3. GWR
# ---------------------------------------------------------------------------
xs <- c("alfabetizacion", "preta_parda", "banos_2mas", "mayores_60", "urbano")
d3 <- mun[complete.cases(st_drop_geometry(mun)[, c("lula_2v", xs)]), ]
d3 <- st_transform(d3, 5880)                                   # SIRGAS 2000 / Brazil Polyconic (metros)
for (x in xs) d3[[paste0("z_", x)]] <- as.numeric(scale(d3[[x]]))
f <- as.formula(paste("lula_2v ~", paste(paste0("z_", xs), collapse = " + ")))
pts <- st_centroid(d3)
sp_d <- as(pts, "Spatial")
ols <- lm(f, data = st_drop_geometry(d3))
msg("GWR: eligiendo ancho de banda (n = %d)...", nrow(d3))
bw <- bw.gwr(f, data = sp_d, approach = "AICc", kernel = "bisquare", adaptive = TRUE)
g <- gwr.basic(f, data = sp_d, bw = bw, kernel = "bisquare", adaptive = TRUE)
sdf <- as.data.frame(g$SDF)
gw <- data.frame(codigo = d3$codigo, gwr_r2 = sdf$Local_R2)
for (x in xs) gw[[paste0("gwr_", x)]] <- sdf[[paste0("z_", x)]]
mun <- merge(mun, gw, by = "codigo", all.x = TRUE)
res$gwr <- list(n = nrow(d3), vecinos = bw, r2_ols = summary(ols)$r.squared, r2_gwr = g$GW.diagnostic$gw.R2,
                aicc_ols = AIC(ols) + 2 * (length(xs) + 2) * (length(xs) + 3) / (nrow(d3) - length(xs) - 3),
                aicc_gwr = g$GW.diagnostic$AICc,
                coef_ols = as.list(coef(ols)[-1]),
                coef_local = lapply(setNames(xs, xs), function(x) as.list(quantile(gw[[paste0("gwr_", x)]], c(.1, .5, .9)))),
                coef_por_uf = lapply(setNames(xs, xs), function(x) as.list(tapply(gw[[paste0("gwr_", x)]], d3$uf, median))))
msg("GWR: %d vecinos; R² MCO %.3f -> GWR %.3f", bw, res$gwr$r2_ols, res$gwr$r2_gwr)

# ---------------------------------------------------------------------------
# 4. SKATER por estado
# ---------------------------------------------------------------------------
vs <- c("lula_2v", "lula_1v", "cambio_2018_2022", "abstencion_2v")
mun$region_skater <- NA_integer_
res$skater <- list()
for (uf in sort(unique(mun$uf))) {
  s <- mun[mun$uf == uf & complete.cases(st_drop_geometry(mun)[, vs]), ]
  if (nrow(s) < 3) next
  # islas sin vecinos (Fernando de Noronha, Ilhabela) y grupos desconectados rompen SKATER: se usa el
  # componente conexo principal y lo demás queda sin región
  nbs <- suppressWarnings(poly2nb(s, queen = TRUE))
  comp <- n.comp.nb(nbs)$comp.id
  s <- s[comp == as.integer(names(which.max(table(comp)))), ]
  k_ibge <- nrow(st_read(file.path(geo, uf, "regioes_imediatas.geojson"), quiet = TRUE))
  k <- min(k_ibge, floor(nrow(s) / 3))
  if (k < 2) next
  ws <- queen_weights(s)
  dat <- as.data.frame(scale(st_drop_geometry(s)[, vs]))
  sk <- skater(k, ws, dat)
  s$region_skater <- sk$Clusters
  mun$region_skater[match(s$codigo, mun$codigo)] <- sk$Clusters
  res$skater[[uf]] <- list(k = k, regioes_imediatas = k_ibge, ratio_entre_total = sk$`The ratio of between to total sum of squares`)
}
msg("SKATER: %d estados", length(res$skater))

# ---------------------------------------------------------------------------
# 5. Accesibilidad y abstención
# ---------------------------------------------------------------------------
va <- c("abstencion_2v", "dist_km", "urbano", "alfabetizacion", "mayores_60", "banos_2mas")
d5 <- mun[complete.cases(st_drop_geometry(mun)[, va]) & mun$dist_km > 0, ]
nb5 <- poly2nb(d5, queen = TRUE)
lw5 <- nb2listw(nb5, style = "W", zero.policy = TRUE)
f5 <- abstencion_2v ~ log(dist_km) + urbano + alfabetizacion + mayores_60 + banos_2mas
ols5 <- lm(f5, data = st_drop_geometry(d5))
sem <- errorsarlm(f5, data = st_drop_geometry(d5), listw = lw5, zero.policy = TRUE, method = "Matrix")
ss <- summary(sem)
res$accesibilidad_municipios <- list(n = nrow(d5), ols = as.list(coef(ols5)), sem = as.list(coef(sem)),
                                     sem_se_logdist = ss$Coef["log(dist_km)", "Std. Error"],
                                     sem_p_logdist = ss$Coef["log(dist_km)", "Pr(>|z|)"],
                                     lambda = unname(sem$lambda),
                                     moran_resid_ols = unname(lm.morantest(ols5, lw5, zero.policy = TRUE)$estimate[1]))
msg("Accesibilidad (SEM, municípios): log(dist) = %.3f (p = %.3g)", coef(sem)["log(dist_km)"], res$accesibilidad_municipios$sem_p_logdist)

# Escuelas: MCO con efectos fijos de UF + deciles de distancia
esc <- do.call(rbind, lapply(list.files(nac, "^escuelas_.*\\.gpkg$", full.names = TRUE), function(f) {
  x <- st_read(f, quiet = TRUE); st_drop_geometry(x)
}))
e5 <- esc[complete.cases(esc[, va]) & esc$dist_km > 0 & esc$electores >= 100, ]
fe <- lm(abstencion_2v ~ log(dist_km) + urbano + alfabetizacion + mayores_60 + banos_2mas + factor(uf), data = e5,
         weights = electores)
cf <- summary(fe)$coefficients
res$accesibilidad_escuelas <- list(n = nrow(e5), coef_logdist = cf["log(dist_km)", "Estimate"],
                                   se_logdist = cf["log(dist_km)", "Std. Error"], r2 = summary(fe)$r.squared)
e5$decil <- cut(e5$dist_km, quantile(e5$dist_km, 0:10 / 10), include.lowest = TRUE, labels = FALSE)
dec <- do.call(rbind, lapply(split(e5, e5$decil), function(x)
  data.frame(decil = x$decil[1], dist_km_mediana = median(x$dist_km),
             abstencion = weighted.mean(x$abstencion_2v, x$electores), urbano = weighted.mean(x$urbano, x$electores),
             escuelas = nrow(x))))
write.csv(dec, file.path(out, "accesibilidad_deciles.csv"), row.names = FALSE)
msg("Accesibilidad (escuelas, EF de UF): log(dist) = %.3f", res$accesibilidad_escuelas$coef_logdist)

# ---------------------------------------------------------------------------
# 1b. LISA en las áreas de escuela, estado por estado
# ---------------------------------------------------------------------------
lisas <- list(); res$lisa_escuelas <- list()
for (f in list.files(nac, "^escuelas_.*\\.gpkg$", full.names = TRUE)) {
  x <- st_read(f, quiet = TRUE)
  x <- x[!is.na(x$lula_2v) & x$electores >= 100, ]
  x <- st_make_valid(x)
  if (nrow(x) < 30) next
  wx <- queen_weights(x)
  lx <- local_moran(wx, x["lula_2v"], permutations = PERM, significance_cutoff = ALFA)
  et <- lisa_labels(lx)[lisa_clusters(lx) + 1]
  uf <- x$uf[1]
  lisas[[uf]] <- data.frame(uf = x$uf, cd_municipio = x$cd_municipio, nr_zona = x$nr_zona, nr_local = x$nr_local,
                            lisa = et, p = lisa_pvalues(lx))
  res$lisa_escuelas[[uf]] <- as.list(table(et))
}
write.csv(do.call(rbind, lisas), file.path(out, "escuelas_lisa.csv"), row.names = FALSE)
msg("LISA escuelas: %d estados", length(lisas))

# ---------------------------------------------------------------------------
st_write(st_transform(mun, 4326), file.path(out, "municipios.gpkg"), layer = "municipios", quiet = TRUE, delete_dsn = TRUE)
res$parametros <- list(permutaciones = PERM, alfa = ALFA, gwr_variables = xs, skater_variables = vs, semilla = 2026,
                       r = R.version.string)
write(toJSON(res, auto_unbox = TRUE, digits = 6, pretty = TRUE), file.path(out, "resumen.json"))
msg("Listo: %s", out)
