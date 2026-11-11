function pcm_param_sweep()
%PCM_PARAM_SWEEP  Parametric sweep over PCM properties for generalised analysis.

    P_base = params_materials();

    scenarioType = 'charge';
    bcType       = 'liquid';
    hLevel       = 'mid';

    T_env = P_base.T_coolant;
    t_end = P_base.t_end_charge;

    Tm_shift_C   = [-4, -2, 0, +2, +4];
    L_pcm_values = [120e3, 160e3, 200e3, 240e3, 280e3];
    k_pcm_values = [0.2, 0.8];

    nTm = numel(Tm_shift_C);
    nL  = numel(L_pcm_values);
    nk  = numel(k_pcm_values);
    nPCM = nTm * nL * nk;

    T_peak_C       = zeros(nPCM,1);
    T_end_C        = zeros(nPCM,1);
    t_cross_s      = nan(nPCM,1);
    phi_end        = zeros(nPCM,1);
    E_aux_kJ       = zeros(nPCM,1);
    PCM_utilisation= zeros(nPCM,1);   % integral of phi_pcm(t)/t_end
    safety_margin_C= zeros(nPCM,1);   % 40 - T_peak

    Tm_solid_C = zeros(nPCM,1);
    Tm_liquid_C= zeros(nPCM,1);
    L_pcm_kJkg = zeros(nPCM,1);
    k_pcm_WmK  = zeros(nPCM,1);

    T_threshold_C = 40;
    idx = 0;

    for iTm = 1:nTm
        for iL = 1:nL
            for ik = 1:nk
                idx = idx + 1;

                P = P_base;

                shift = Tm_shift_C(iTm);
                P.Tm_solid  = (29 + shift) + 273.15;
                P.Tm_liquid = (34 + shift) + 273.15;
                P.L_pcm     = L_pcm_values(iL);
                P.k_pcm     = k_pcm_values(ik);

                Tm_solid_C(idx)  = P.Tm_solid  - 273.15;
                Tm_liquid_C(idx) = P.Tm_liquid - 273.15;
                L_pcm_kJkg(idx)  = P.L_pcm / 1e3;
                k_pcm_WmK(idx)   = P.k_pcm;

                res = run_scenario_1D(P, scenarioType, bcType, hLevel, T_env, t_end);

                T_C        = res.Tmax - 273.15;
                T_peak_C(idx) = max(T_C);
                T_end_C(idx)  = T_C(end);
                phi_end(idx)  = res.phi_pcm(end);
                E_aux_kJ(idx) = res.E_aux/1e3;

                % Threshold crossing
                i_cross = find(T_C >= T_threshold_C, 1, 'first');
                if ~isempty(i_cross)
                    t_cross_s(idx) = res.t(i_cross);
                end

                % PCM utilisation index (average phi over event)
                PCM_utilisation(idx) = trapz(res.t, res.phi_pcm) / t_end;

                % Safety margin
                safety_margin_C(idx) = T_threshold_C - T_peak_C(idx);
            end
        end
    end

    PCM_results = table( ...
        Tm_solid_C, Tm_liquid_C, L_pcm_kJkg, k_pcm_WmK, ...
        T_peak_C, T_end_C, t_cross_s, phi_end, E_aux_kJ, ...
        PCM_utilisation, safety_margin_C, ...
        'VariableNames', { ...
            'Tm_solid_C','Tm_liquid_C','L_pcm_kJkg','k_pcm_WmK', ...
            'T_peak_C','T_end_C','t_cross_s','phi_end','E_aux_kJ', ...
            'PCM_utilisation','safety_margin_C'});

    fprintf('\nExample rows from PCM_results:\n');
    disp(PCM_results(1:min(10,height(PCM_results)),:));

    assignin('base','PCM_results',PCM_results);

    % Simple plots (you can expand)
    melting_center_C = (Tm_solid_C + Tm_liquid_C)/2;

    figure; hold on;
    cols = lines(nL);
    for iL = 1:nL
        mask = abs(L_pcm_kJkg - L_pcm_values(iL)/1e3) < 1e-6 & ...
               (k_pcm_WmK == k_pcm_values(1));
        plot(melting_center_C(mask), T_peak_C(mask), 'o-', ...
            'Color', cols(iL,:), ...
            'DisplayName', sprintf('L_{pcm} = %.0f kJ/kg', L_pcm_values(iL)/1e3));
    end
    xlabel('Melting window centre [°C]');
    ylabel('Peak T_{max} [°C]');
    grid on;
    legend('Location','best');
    title('Peak Tmax vs melting centre (baseline k_{pcm})');

    figure; hold on;
    cols = lines(nk);
    for ik = 1:nk
        mask = (k_pcm_WmK == k_pcm_values(ik)) & (Tm_solid_C == 29);
        plot(L_pcm_kJkg(mask), T_peak_C(mask), 'o-', ...
            'Color', cols(ik,:), ...
            'DisplayName', sprintf('k_{pcm} = %.1f W/mK', k_pcm_values(ik)));
    end
    xlabel('PCM latent heat [kJ/kg]');
    ylabel('Peak T_{max} [°C]');
    grid on;
    legend('Location','best');
    title('Peak Tmax vs latent heat (baseline melting window)');
end