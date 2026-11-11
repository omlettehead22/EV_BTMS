function plot_Tmax_curves(resultsStruct)
%PLOT_TMAX_CURVES  Plot Tmax(t) for each scenario.

nSc   = numel(resultsStruct);
figure; hold on;
cols  = lines(nSc);

for k = 1:nSc
    res = resultsStruct(k).outputs;
    plot(res.t, res.Tmax - 273.15, 'Color', cols(k,:), ...
        'DisplayName', resultsStruct(k).name);
end
xlabel('Time [s]');
ylabel('Max cell temperature [°C]');
legend('Location','best');
grid on;
title('Max cell temperature vs time for all scenarios');
end