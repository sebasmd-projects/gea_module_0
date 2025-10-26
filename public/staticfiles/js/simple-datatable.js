window.addEventListener('DOMContentLoaded', event => {
    const tableIds = [
        'profitability_po_table',
        'offers_table',
        'locations_table',
        'asset_and_category_table',
        'offers_table',
        'categories_table',
        'assetinline_table',
        'tblByCategory',
    ];

    const perPage20Tables = [
        'assets_table',
        'tblInventory'
    ];

    tableIds.forEach(id => {
        const table = document.getElementById(id);
        if (table) {
            new simpleDatatables.DataTable(table, {
                perPage: 5,
                perPageSelect: [5, 10, 25, 50]
            });
        }
    });

    perPage20Tables.forEach(id => {
        const table = document.getElementById(id);
        if (table) {
            new simpleDatatables.DataTable(table, {
                perPage: 20,
                perPageSelect: [10, 20, 50, 100]
            });
        }
    });
});